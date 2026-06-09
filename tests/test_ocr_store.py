from ocr_store import PageResult, OcrResult, save_ocr_result, load_ocr_result


def test_roundtrip(tmp_path):
    pages = [
        PageResult(index=0, kind="ocr", table_htmls=["<table><tr><td>A</td></tr></table>"],
                   text_blocks=["hello"], image="p1.png"),
        PageResult(index=1, kind="text", table_htmls=[], text_blocks=["body"], image=None),
    ]
    res = OcrResult(source=r"C:\docs\x.pdf", pages=pages)
    path = save_ocr_result(tmp_path, "x", res)
    assert path.exists()
    loaded = load_ocr_result(path)
    assert loaded.source == res.source
    assert len(loaded.pages) == 2
    assert loaded.pages[0].table_htmls[0].startswith("<table")
    assert loaded.pages[1].kind == "text"
