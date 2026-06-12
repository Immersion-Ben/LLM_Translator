"""OCR 속도 벤치마크: 현재 구성 vs mkldnn on vs mobile 모델.

사용: python bench_ocr.py <config>
  config: base | mkldnn | mobile | mobile_mkldnn
결과는 bench_results.txt 에 append.
"""
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "False")

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "bench_results.txt"
PAGE = HERE / "bench_page.png"

SERVER_MODELS = {
    "layout_detection_model_name": "PP-DocLayout-L",
    "table_classification_model_name": "PP-LCNet_x1_0_table_cls",
    "wired_table_structure_recognition_model_name": "SLANeXt_wired",
    "wired_table_cells_detection_model_name": "RT-DETR-L_wired_table_cell_det",
    "doc_orientation_classify_model_name": "PP-LCNet_x1_0_doc_ori",
    "text_detection_model_name": "PP-OCRv4_server_det",
    "text_recognition_model_name": "PP-OCRv4_server_rec_doc",
}
MOBILE_MODELS = {
    **SERVER_MODELS,
    "layout_detection_model_name": "PP-DocLayout-S",
    "text_detection_model_name": "PP-OCRv5_mobile_det",
    "text_recognition_model_name": "PP-OCRv5_mobile_rec",
}

CONFIGS = {
    "base": (SERVER_MODELS, False),
    "mkldnn": (SERVER_MODELS, True),
    "mobile": (MOBILE_MODELS, False),
    "mobile_mkldnn": (MOBILE_MODELS, True),
}


def make_page() -> None:
    """200DPI A4 비슷한 밀도의 합성 페이지: 본문 ~50줄 + 유선 표 1개."""
    if PAGE.exists():
        return
    from PIL import Image, ImageDraw, ImageFont
    W, H = 1654, 2339
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)

    def load(path, size):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            return ImageFont.load_default()

    f_zh = load("C:/Windows/Fonts/simsun.ttc", 30)
    f_en = load("C:/Windows/Fonts/arial.ttf", 30)

    zh = "本公司二零二五年度第三季度营业收入较去年同期增长百分之十二点五。"
    en = "Quarterly revenue increased by 12.5 percent compared to last year."
    y = 80
    for i in range(50):
        if i % 2 == 0:
            d.text((100, y), f"{i+1:02d}. {zh}", fill="black", font=f_zh)
        else:
            d.text((100, y), f"{i+1:02d}. {en}", fill="black", font=f_en)
        y += 38
    # 유선 표 6행 x 4열
    tx, ty, cw, ch, rows, cols = 100, y + 40, 360, 52, 6, 4
    for r in range(rows + 1):
        d.line([(tx, ty + r * ch), (tx + cw * cols, ty + r * ch)], fill="black", width=2)
    for c in range(cols + 1):
        d.line([(tx + c * cw, ty), (tx + c * cw, ty + ch * rows)], fill="black", width=2)
    head = ["项目", "数量", "单价", "金额"]
    for c, v in enumerate(head):
        d.text((tx + c * cw + 12, ty + 12), v, fill="black", font=f_zh)
    for r in range(1, rows):
        for c in range(cols):
            d.text((tx + c * cw + 12, ty + r * ch + 12), f"A{r}{c} 1234", fill="black", font=f_en)
    img.save(str(PAGE))


def log(msg: str) -> None:
    with RESULTS.open("a", encoding="utf-8") as f:
        f.write(msg + "\n")
    print(msg, flush=True)


def main() -> None:
    name = sys.argv[1]
    models, mkldnn = CONFIGS[name]
    make_page()
    log(f"--- config={name} mkldnn={mkldnn} ---")
    try:
        t0 = time.perf_counter()
        from paddleocr import TableRecognitionPipelineV2
        kw = {
            "use_doc_orientation_classify": True,
            "use_doc_unwarping": False,
            "use_layout_detection": True,
            "enable_mkldnn": mkldnn,
            "cpu_threads": 8,
        }
        kw.update(models)
        pipe = TableRecognitionPipelineV2(**kw)
        t1 = time.perf_counter()
        log(f"init: {t1 - t0:.1f}s")

        def predict():
            tables, texts = 0, 0
            for res in pipe.predict(str(PAGE)):
                tables += len(res.get("table_res_list") or [])
                ocr = res.get("overall_ocr_res")
                if ocr:
                    texts += len([s for s in (ocr.get("rec_texts") or []) if s.strip()])
            return tables, texts

        t2 = time.perf_counter()
        tables, texts = predict()
        t3 = time.perf_counter()
        log(f"predict#1: {t3 - t2:.1f}s  tables={tables} texts={texts}")
        t4 = time.perf_counter()
        tables, texts = predict()
        t5 = time.perf_counter()
        log(f"predict#2: {t5 - t4:.1f}s  tables={tables} texts={texts}")
        log(json.dumps({"config": name, "init_s": round(t1 - t0, 1),
                        "p1_s": round(t3 - t2, 1), "p2_s": round(t5 - t4, 1),
                        "tables": tables, "texts": texts}))
    except Exception as e:  # noqa: BLE001
        log(f"FAIL: {type(e).__name__}: {e}")
        log(traceback.format_exc()[-2000:])


if __name__ == "__main__":
    main()
