"""Generate deterministic DXF fixtures; never use customer files."""

from __future__ import annotations

from pathlib import Path

import cv2
import ezdxf
import numpy as np

HERE = Path(__file__).resolve().parent / "generated"


def save(doc, name: str) -> Path:
    path = HERE / name
    doc.saveas(path)
    return path


def simple(version: str, name: str) -> None:
    doc = ezdxf.new(version, setup=True)
    doc.modelspace().add_line((0, 0), (100, 50))
    doc.modelspace().add_text("ação Ω", dxfattribs={"height": 2.5}).set_placement((5, 5))
    save(doc, name)


def gap_002() -> None:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_line((0.02, 0), (100, 0))
    msp.add_line((100, 0), (100, 50))
    msp.add_line((100, 50), (0, 50))
    msp.add_line((0, 50), (0, 0))
    save(doc, "gap_002.dxf")


def multi_network() -> None:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    for start, end in (
        ((0, 0), (100, 0)),
        ((100, 0), (100, 50)),
        ((100, 50), (0, 50)),
        ((0, 50), (0, 0)),
        ((200, 0), (220, 0)),
        ((220, 0), (240, 10)),
    ):
        msp.add_line(start, end)
    save(doc, "multi_rede.dxf")


def layer_states() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.new("AUXILIAR")
    doc.layers.new("RASCUNHO")
    doc.layers.get("AUXILIAR").off()
    doc.layers.get("RASCUNHO").freeze()
    msp = doc.modelspace()
    msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "AUXILIAR"})
    msp.add_line((0, 1), (1, 1), dxfattribs={"layer": "RASCUNHO"})
    msp.add_line((0, 2), (1, 2), dxfattribs={"layer": "CORTE"})
    save(doc, "camadas_ocultas.dxf")


def block_cycle() -> None:
    doc = ezdxf.new("R2018", setup=True)
    block_a = doc.blocks.new("A")
    block_b = doc.blocks.new("B")
    block_a.add_blockref("B", (0, 0))
    block_b.add_blockref("A", (0, 0))
    doc.modelspace().add_blockref("A", (0, 0))
    save(doc, "ciclo_blocos.dxf")


def name_collision() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.new("Corte")
    doc.layers.new("CORTE2")
    source = save(doc, "_name_source.dxf")
    text = source.read_text(encoding="utf-8")
    marker = "\n  2\nCORTE2\n"
    if marker not in text:
        raise RuntimeError("could not find CORTE2 table entry")
    text = text.replace(marker, "\n  2\nCORTE\n", 1)
    (HERE / "nome_colidente.dxf").write_text(text, encoding="utf-8")
    source.unlink()


def custom_data() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.appids.new("THIRD_PARTY")
    line = doc.modelspace().add_line((0, 0), (1, 1))
    line.set_xdata(
        "THIRD_PARTY",
        [(1000, "payload"), (1070, 42), (1005, "FFFF")],
    )
    xdict = line.new_extension_dict()
    xrecord = xdict.add_xrecord("CONFIG")
    xrecord.tags = [(1, "value"), (90, 7)]
    save(doc, "custom_data.dxf")


def unit_blocks() -> None:
    doc = ezdxf.new("R2018", setup=True, units=4)
    block = doc.blocks.new("INCH_PART")
    block.block_record.dxf.units = 1
    block.add_line((0, 0), (1, 0))
    doc.modelspace().add_blockref("INCH_PART", (0, 0))
    save(doc, "unit_blocks.dxf")


def formatting() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.layers.new("RED", dxfattribs={"color": 1, "lineweight": 50})
    msp = doc.modelspace()
    msp.add_line((0, 0), (10, 0), dxfattribs={"layer": "RED"})
    msp.add_circle((5, 5), 2, dxfattribs={"color": 3, "lineweight": 35})
    save(doc, "formatting.dxf")


def text() -> None:
    doc = ezdxf.new("R2018", setup=True)
    msp = doc.modelspace()
    msp.add_text("Plain", dxfattribs={"height": 2.5}).set_placement((0, 0))
    msp.add_mtext(r"{\\C1;Red}\\P\\H2x;Tall\\S1/2;", dxfattribs={"char_height": 2.5})
    save(doc, "text.dxf")


def mesh() -> None:
    doc = ezdxf.new("R2018", setup=True)
    mesh_entity = doc.modelspace().add_mesh()
    with mesh_entity.edit_data() as mesh_data:
        mesh_data.vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)]
        mesh_data.faces = [(0, 1, 2), (0, 1, 3), (1, 2, 3), (2, 0, 3)]
    save(doc, "mesh.dxf")


def xref_source() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.modelspace().add_circle((0, 0), 5)
    save(doc, "xref_source.dxf")


def corrupted() -> None:
    doc = ezdxf.new("R2018", setup=True)
    doc.modelspace().add_line((0, 0), (1, 1))
    source = save(doc, "_corrupt_source.dxf")
    lines = source.read_text(encoding="utf-8").splitlines()
    lines = lines[:-4]  # remove final ENDSEC/EOF markers
    (HERE / "corrompido.dxf").write_text("\n".join(lines) + "\n", encoding="utf-8")
    source.unlink()


def image_components() -> None:
    """Create PNG/JPG inputs with geometry, a hole, a circle, and printed text."""
    image = np.full((500, 800, 3), 255, dtype=np.uint8)
    cv2.rectangle(image, (50, 130), (300, 400), (0, 0, 0), thickness=-1)
    cv2.circle(image, (175, 265), 55, (255, 255, 255), thickness=-1)
    cv2.circle(image, (560, 290), 85, (0, 0, 0), thickness=-1)
    cv2.putText(
        image,
        "MOTOR 25",
        (365, 90),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.5,
        (0, 0, 0),
        thickness=3,
        lineType=cv2.LINE_AA,
    )
    png_ok, png = cv2.imencode(".png", image)
    jpg_ok, jpg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    if not png_ok or not jpg_ok:
        raise RuntimeError("OpenCV could not encode image fixtures")
    png.tofile(HERE / "componentes.png")
    jpg.tofile(HERE / "componentes.jpg")


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    for suffix in ("*.dxf", "*.png", "*.jpg"):
        for existing in HERE.glob(suffix):
            existing.unlink()
    simple("R2000", "r2000.dxf")
    simple("R2007", "r2007.dxf")
    gap_002()
    multi_network()
    layer_states()
    block_cycle()
    name_collision()
    custom_data()
    unit_blocks()
    formatting()
    text()
    mesh()
    xref_source()
    corrupted()
    image_components()
    print(
        f"generated {len(list(HERE.glob('*.dxf')))} DXF and "
        f"{len(list(HERE.glob('*.png'))) + len(list(HERE.glob('*.jpg')))} image fixtures "
        f"in {HERE}"
    )


if __name__ == "__main__":
    main()
