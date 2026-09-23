"""Asset and icon loading utility for MediaFlow GUI."""

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

from app.gui.styles import COLORS

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOGO_DIR = PROJECT_ROOT / "assets" / "logo"


def get_logo_image(size: int = 32) -> QImage:
    """Return an application logo QImage of the specified square size.

    Prioritizes vector assets/logo/logo.svg rendered with QSvgRenderer for
    high-DPI fidelity, followed by raster files (png, ico, webp, jpg),
    and falls back to an antialiased monogram emblem.
    """
    # 1. Prioritize vector SVG logo
    svg_path = LOGO_DIR / "logo.svg"
    if svg_path.is_file() and svg_path.stat().st_size > 0:
        try:
            from PySide6.QtSvg import QSvgRenderer

            renderer = QSvgRenderer(str(svg_path))
            if renderer.isValid():
                image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                renderer.render(painter)
                painter.end()
                if not image.isNull():
                    return image
        except Exception:
            pass

    # 2. Check for standard raster images
    for filename in ("logo.png", "logo.ico", "logo.webp", "logo.jpg"):
        candidate = LOGO_DIR / filename
        if candidate.is_file() and candidate.stat().st_size > 0:
            image = QImage(str(candidate))
            if not image.isNull():
                return image.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

    # Render clean geometric monogram emblem using QImage
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Base rounded background container
    radius = size * 0.22
    rect = QRectF(1.0, 1.0, float(size - 2), float(size - 2))

    path = QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    painter.fillPath(path, QBrush(QColor(COLORS.accent_primary)))

    # Stylized clean 'M' path with flow arrow
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(2.0, size * 0.11))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    # Left leg, center notch, right leg
    p1 = QPointF(size * 0.26, size * 0.72)
    p2 = QPointF(size * 0.26, size * 0.32)
    p3 = QPointF(size * 0.50, size * 0.54)
    p4 = QPointF(size * 0.74, size * 0.32)
    p5 = QPointF(size * 0.74, size * 0.72)

    m_path = QPainterPath()
    m_path.moveTo(p1)
    m_path.lineTo(p2)
    m_path.lineTo(p3)
    m_path.lineTo(p4)
    m_path.lineTo(p5)

    painter.drawPath(m_path)
    painter.end()

    return image


def get_logo_pixmap(size: int = 32) -> QPixmap:
    """Return an application logo pixmap of the specified square size."""
    image = get_logo_image(size)
    return QPixmap.fromImage(image)


def get_app_icon() -> QIcon:
    """Retrieve the application icon, with automatic vector fallback.

    Checks for assets/logo/icon.ico, then assets/logo/logo.png. If neither
    exists, renders a crisp native geometric vector icon.
    """
    ico_path = LOGO_DIR / "icon.ico"
    if ico_path.is_file() and ico_path.stat().st_size > 0:
        icon = QIcon(str(ico_path))
        if not icon.isNull():
            return icon

    png_path = LOGO_DIR / "logo.png"
    if png_path.is_file() and png_path.stat().st_size > 0:
        icon = QIcon(str(png_path))
        if not icon.isNull():
            return icon

    # Fallback to programmatic high-resolution vector icon
    pixmap = get_logo_pixmap(size=256)
    return QIcon(pixmap)


def create_vector_image(icon_name: str, color: Optional[str] = None, size: int = 20) -> QImage:
    """Render a clean, native line icon on a QImage.

    Args:
        icon_name: Icon identifier ('downloader', 'history', 'settings', 'license',
                   'folder', 'play', 'cancel', 'retry').
        color: Stroke color override (defaults to secondary text color).
        size: Target icon canvas size.

    Returns:
        QImage instance with crisp antialiased rendering.
    """
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)

    stroke_color = QColor(color or COLORS.text_secondary)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    pen = QPen(stroke_color)
    pen.setWidthF(1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    margin = size * 0.2
    w = size - 2 * margin
    h = size - 2 * margin

    if icon_name == "downloader":
        # Downward download arrow into tray
        cx = size / 2
        painter.drawLine(QPointF(cx, margin), QPointF(cx, margin + h * 0.65))
        painter.drawLine(QPointF(cx - w * 0.3, margin + h * 0.38), QPointF(cx, margin + h * 0.65))
        painter.drawLine(QPointF(cx + w * 0.3, margin + h * 0.38), QPointF(cx, margin + h * 0.65))
        tray_y = margin + h
        painter.drawLine(QPointF(margin, tray_y), QPointF(margin + w, tray_y))

    elif icon_name == "history":
        # Clock circle with hands
        cx = size / 2
        cy = size / 2
        r = w / 2
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.drawLine(QPointF(cx, cy), QPointF(cx, cy - r * 0.55))
        painter.drawLine(QPointF(cx, cy), QPointF(cx + r * 0.45, cy))

    elif icon_name == "settings":
        # Clean gear geometry: circle with ticks
        cx = size / 2
        cy = size / 2
        r_inner = w * 0.25
        r_outer = w * 0.48
        painter.drawEllipse(QPointF(cx, cy), r_inner, r_inner)
        painter.drawEllipse(QPointF(cx, cy), r_outer, r_outer)

    elif icon_name == "license":
        # Shield geometry
        shield = QPainterPath()
        shield.moveTo(size * 0.5, margin)
        shield.lineTo(size - margin, margin + h * 0.25)
        shield.quadTo(size - margin, size - margin, size * 0.5, size - margin)
        shield.quadTo(margin, size - margin, margin, margin + h * 0.25)
        shield.closeSubpath()
        painter.drawPath(shield)

    elif icon_name == "folder":
        # Minimal folder outline
        folder = QPainterPath()
        folder.moveTo(margin, margin + h * 0.2)
        folder.lineTo(margin + w * 0.4, margin + h * 0.2)
        folder.lineTo(margin + w * 0.55, margin + h * 0.35)
        folder.lineTo(margin + w, margin + h * 0.35)
        folder.lineTo(margin + w, margin + h)
        folder.lineTo(margin, margin + h)
        folder.closeSubpath()
        painter.drawPath(folder)

    elif icon_name == "play":
        # Right-facing play triangle
        triangle = QPainterPath()
        triangle.moveTo(margin + w * 0.2, margin)
        triangle.lineTo(margin + w * 0.9, size / 2)
        triangle.lineTo(margin + w * 0.2, margin + h)
        triangle.closeSubpath()
        painter.fillPath(triangle, QBrush(stroke_color))

    elif icon_name == "cancel":
        # Crisp X cross
        painter.drawLine(QPointF(margin, margin), QPointF(margin + w, margin + h))
        painter.drawLine(QPointF(margin + w, margin), QPointF(margin, margin + h))

    elif icon_name == "retry":
        # Circular reload arc with arrow
        cx = size / 2
        cy = size / 2
        r = w * 0.45
        rect_arc = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        painter.drawArc(rect_arc, 45 * 16, 270 * 16)
        arrow_tip = QPointF(cx + r, cy)
        painter.drawLine(arrow_tip, QPointF(arrow_tip.x() - 3, arrow_tip.y() - 3))
        painter.drawLine(arrow_tip, QPointF(arrow_tip.x() + 3, arrow_tip.y() - 3))

    else:
        # Generic dot
        painter.drawEllipse(QPointF(size / 2, size / 2), 3, 3)

    painter.end()
    return image


def create_vector_icon(icon_name: str, color: Optional[str] = None, size: int = 20) -> QIcon:
    """Render a clean, native line QIcon."""
    image = create_vector_image(icon_name=icon_name, color=color, size=size)
    return QIcon(QPixmap.fromImage(image))
