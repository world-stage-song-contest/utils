from pathlib import Path
import xml.etree.ElementTree as ET

def create_element(tag: str, text: str | None = None, **attributes: str) -> ET.Element:
    element = ET.Element(tag)
    if attributes:
        for key, value in attributes.items():
            element.set(key.replace('_', '-'), value)
    if text:
        element.text = text
    return element

def svg(width: float, height: float, **attributes: str) -> ET.Element:
    return create_element(
        'svg',
        xmlns='http://www.w3.org/2000/svg',
        width=str(width),
        height=str(height),
        viewBox=f'0 0 {width} {height}',
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

def save(svg: ET.Element, filename: Path) -> None:
    tree = ET.ElementTree(svg)
    tree.write(filename, encoding='utf-8', xml_declaration=True)