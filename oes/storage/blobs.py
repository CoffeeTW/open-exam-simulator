"""圖片資料與 JSON 分開存放（題庫檔、作答紀錄共用）。

記憶體中的題目維持原本格式：images 清單的每張圖片為 {"id", "mime", "data"(base64), "width"?}。
寫入資料庫時，把 data 取出存成二進位（省去 base64 多出的約 33%），內容相同的圖片只存一份；
JSON 中改記 {"blob": SHA-256}。讀取時再換回 data，其他程式碼不需要知道這件事。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Any, Callable

BLOB_KEY = "blob"


def _is_image(value: Any) -> bool:
    return isinstance(value, dict) and isinstance(value.get("mime"), str) and "id" in value


def externalize(value: Any, blobs: dict[str, tuple[str, bytes]]) -> Any:
    """回傳複本：所有 images 清單中圖片的 data 換成 blob 雜湊；圖片內容加入 blobs（雜湊 → (mime, 位元組)）。

    原物件不會被修改；data 不是有效 base64 的圖片維持原樣。
    """
    if isinstance(value, list):
        return [externalize(item, blobs) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key == "images" and isinstance(item, list):
            result[key] = [_externalize_image(image, blobs) for image in item]
        else:
            result[key] = externalize(item, blobs)
    return result


def _externalize_image(image: Any, blobs: dict[str, tuple[str, bytes]]) -> Any:
    if not _is_image(image) or not isinstance(image.get("data"), str) or BLOB_KEY in image:
        return externalize(image, blobs)
    try:
        raw = base64.b64decode(image["data"], validate=True)
    except (ValueError, binascii.Error):
        return dict(image)
    digest = hashlib.sha256(raw).hexdigest()
    blobs.setdefault(digest, (image["mime"], raw))
    copy = {k: v for k, v in image.items() if k != "data"}
    copy[BLOB_KEY] = digest
    return copy


def blob_refs(value: Any) -> set[str]:
    """JSON 結構中引用的所有圖片雜湊。"""
    refs: set[str] = set()
    if isinstance(value, list):
        for item in value:
            refs |= blob_refs(item)
    elif isinstance(value, dict):
        if _is_image(value) and isinstance(value.get(BLOB_KEY), str):
            refs.add(value[BLOB_KEY])
        for item in value.values():
            refs |= blob_refs(item)
    return refs


def internalize(value: Any, fetch: Callable[[set[str]], dict[str, bytes]]) -> Any:
    """把 blob 雜湊換回 base64 data（就地修改並回傳）。找不到的圖片 data 設為空字串（顯示為無法顯示的圖片）。"""
    refs = blob_refs(value)
    if not refs:
        return value
    found = fetch(refs)
    encoded = {digest: base64.b64encode(raw).decode("ascii") for digest, raw in found.items()}

    def walk(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                walk(child)
        elif isinstance(item, dict):
            if _is_image(item) and isinstance(item.get(BLOB_KEY), str):
                digest = item.pop(BLOB_KEY)
                fields = list(item.items())
                item.clear()
                for key, child in fields:  # data 放回 mime 之後，與原本格式相同
                    item[key] = child
                    if key == "mime":
                        item["data"] = encoded.get(digest, "")
            for child in item.values():
                walk(child)
    walk(value)
    return value
