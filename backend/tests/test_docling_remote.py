"""Unit tests for docling-serve HTTP client helpers."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from services.docling_remote import (
    _DEFAULT_CONVERT_OPTIONS,
    _embed_pictures_in_doc_dict,
    _encode_multipart_options,
    _extract_json_content,
    _payload_from_zip,
    _resolve_asset_path,
    load_document_from_response,
)


def test_encode_multipart_options_flattens_lists_and_bools():
    parts = _encode_multipart_options(
        {
            "to_formats": ["md", "json"],
            "include_images": True,
            "images_scale": 2.0,
        }
    )
    assert ("to_formats", "md") in parts
    assert ("to_formats", "json") in parts
    assert ("include_images", "true") in parts
    assert ("images_scale", "2.0") in parts
    assert not any(key == "options" for key, _ in parts)


def test_default_options_use_referenced_and_zip_target_field_available():
    assert _DEFAULT_CONVERT_OPTIONS["image_export_mode"] == "referenced"


def test_extract_json_content_from_document_block():
    payload = {
        "status": "success",
        "document": {"md_content": "# Hi", "json_content": {"name": "doc", "pictures": []}},
    }
    assert _extract_json_content(payload) == {"name": "doc", "pictures": []}


def test_extract_json_content_ignores_empty_json_object():
    payload = {"document": {"md_content": "x", "json_content": {}}}
    assert _extract_json_content(payload) is None


def test_load_document_from_response_raises_on_missing_json():
    with pytest.raises(ValueError, match="json_content"):
        load_document_from_response(
            {"status": "success", "document": {"md_content": "hello"}}
        )


def test_load_document_from_response_raises_on_failure_status():
    with pytest.raises(RuntimeError, match="failure"):
        load_document_from_response(
            {
                "status": "failure",
                "errors": ["layout model OOM"],
                "document": {"md_content": ""},
            }
        )


def test_resolve_asset_path_finds_artifacts_subdir(tmp_path: Path):
    assets = tmp_path / "artifacts"
    assets.mkdir()
    png = assets / "image_000001_test.png"
    Image.new("RGB", (100, 100), color="red").save(png)
    found = _resolve_asset_path(tmp_path, "image_000001_test.png")
    assert found == png


def test_embed_pictures_in_doc_dict_sets_data_uri(tmp_path: Path):
    assets = tmp_path / "artifacts"
    assets.mkdir()
    name = "image_000001_test.png"
    Image.new("RGB", (120, 120), color="blue").save(assets / name)

    doc_dict = {
        "schema_name": "DoclingDocument",
        "pictures": [
            {
                "image": {
                    "mimetype": "image/png",
                    "dpi": 144,
                    "size": {"width": 120, "height": 120},
                    "uri": name,
                }
            }
        ],
    }
    n = _embed_pictures_in_doc_dict(doc_dict, tmp_path)
    assert n == 1
    assert str(doc_dict["pictures"][0]["image"]["uri"]).startswith("data:image/png;base64,")


def test_payload_from_zip_api_shaped_response(tmp_path: Path):
  buf = io.BytesIO()
  root_name = "out"
  with zipfile.ZipFile(buf, "w") as zf:
      doc = {
          "status": "success",
          "document": {
              "json_content": {
                  "schema_name": "DoclingDocument",
                  "pictures": [
                      {
                          "image": {
                              "mimetype": "image/png",
                              "dpi": 72,
                              "size": {"width": 90, "height": 90},
                              "uri": "image_000000_abc.png",
                          }
                      }
                  ],
              },
          },
      }
      zf.writestr(f"{root_name}/result.json", json.dumps(doc))
      img = Image.new("RGB", (90, 90), color="green")
      img_bytes = io.BytesIO()
      img.save(img_bytes, format="PNG")
      zf.writestr(f"{root_name}/artifacts/image_000000_abc.png", img_bytes.getvalue())

  payload = _payload_from_zip(buf.getvalue())
  assert payload["status"] == "success"
  uri = payload["document"]["json_content"]["pictures"][0]["image"]["uri"]
  assert str(uri).startswith("data:image/png;base64,")
