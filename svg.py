from pathlib import Path
import xml.etree.ElementTree as ET

def create_element(tag: str, text: str | None = None, **attributes: str) -> ET.Element:
    element = ET.Element(tag)
    if attributes:
        for key, value in attributes.items():
            element.set(key.strip('_').replace('_', '-'), value)
    if text:
        element.text = text
    return element

def svg(width: float, height: float, vb_width: float, vb_height: float, **attributes: str) -> ET.Element:
    return create_element(
        'svg',
        xmlns='http://www.w3.org/2000/svg',
        width=f"{width:.3f}",
        height=f"{height:.3f}",
        viewBox=f'0 0 {vb_width:.3f} {vb_height:.3f}',
        **attributes
    )

def text(text: str, font_size: float, x: float, y: float,font_family='Arial', fill='black', **attributes) -> ET.Element:
    return create_element(
        'text',
        text,
        x=str(x),
        y=str(y),
        font_size=str(font_size),
        font_family=font_family,
        fill=fill,
        **attributes
    )

def circle(cx: float, cy: float, r: float, fill='none', stroke='black', stroke_width: float=0) -> ET.Element:
    return create_element(
        'circle',
        cx=str(cx),
        cy=str(cy),
        r=str(r),
        fill=fill,
        stroke=stroke,
        stroke_width=str(stroke_width)
    )

def rectangle(x: float, y: float, width: float, height: float, fill='none', stroke='black', stroke_width: float=0) -> ET.Element:
    return create_element(
        'rect',
        x=str(x),
        y=str(y),
        width=str(width),
        height=str(height),
        fill=fill,
        stroke=stroke,
        stroke_width=str(stroke_width)
    )

def line(x1: float, y1: float, x2: float, y2: float, stroke='black', stroke_width: float = 1) -> ET.Element:
    return create_element(
        'line',
        x1=str(x1),
        y1=str(y1),
        x2=str(x2),
        y2=str(y2),
        stroke=stroke,
        stroke_width=str(stroke_width)
    )

def image(x: float, y: float, width: float, height: float, path: Path):
    return create_element(
        'image',
        x=str(x),
        y=str(y),
        width=str(width),
        height=str(height),
        href=path.absolute().as_uri()
    )

def defs():
    return create_element('defs')

def filter(id: str, **attributes: str):
    return create_element(
        'filter',
        id=id,
        **attributes
    )

def fe_gaussian_blur(_in: str, std_deviation: float, result: str):
    return create_element(
        'feGaussianBlur',
        _in=_in,
        stdDeviation=str(std_deviation),
        result=result
    )

def fe_flood(_in: str, flood_color: str, flood_opacity: float, result: str):
    return create_element(
        'feFlood',
        _in=_in,
        flood_color=flood_color,
        flood_opacity=str(flood_opacity),
        result=result
    )

def fe_offset(_in: str, dx: float, dy: float, result: str):
    return create_element(
        'feOffset',
        _in=_in,
        dx=str(dx),
        dy=str(dy),
        result=result
    )

def fe_composite(_in: str, _in2: str, result: str, operator: str = "over"):
    return create_element(
        'feComposite',
        _in=_in,
        _in2=_in2,
        operator=operator,
        result=result
    )

def save(svg: ET.Element, filename: Path) -> None:
    tree = ET.ElementTree(svg)
    tree.write(filename, encoding='utf-8', xml_declaration=True)