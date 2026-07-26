import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import streamlit as st
import re
from collections import Counter

st.set_page_config(page_title="PDF Line Recolorer", layout="wide")
st.title("🟡 Advanced PDF Line Recolorer")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Processing Controls")

engine_mode = st.sidebar.radio(
    "Recoloring Engine",
    options=["Raster (Image-Based)", "Vector (Native PDF Shapes)"],
    help="Choose Raster for scans and flattened drawings. Choose Vector for CAD exports and digital PDFs to keep text searchable and file sizes small."
)

target_hex = st.sidebar.color_picker("Line Color", "#FFF200")
bg_hex = st.sidebar.color_picker("Background Color (Raster Only)", "#FFFFFF")

if engine_mode == "Raster (Image-Based)":
    threshold = st.sidebar.slider("Line Sensitivity", min_value=150, max_value=255, value=240, help="Lower = thinner lines, Higher = thicker/fainter lines")
    dpi_setting = st.sidebar.select_slider("Export DPI", options=[150, 300, 450], value=300)

def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return np.array([int(h[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)

def hex_to_float_rgb(hex_str):
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

LINE_COLOR = hex_to_rgb(target_hex)
BG_COLOR = hex_to_rgb(bg_hex)
FLOAT_LINE_COLOR = hex_to_float_rgb(target_hex)

# --- ENGINE EXPLANATION BANNER ---
if engine_mode == "Vector (Native PDF Shapes)":
    st.info(
        "💡 **Vector Mode Active:** Ideal for digital CAD exports (AutoCAD, Revit) and native PDF vector files. "
        "It modifies native stroke/fill operators, preserves vector sharpness, and keeps text searchable."
    )
else:
    st.info(
        "💡 **Raster Mode Active:** Ideal for scanned paper drawings, images, or flattened PDFs. "
        "It processes every pixel directly to guarantee all drawing lines turn yellow."
    )

uploaded_file = st.file_uploader("Upload your PDF file", type=["pdf"])


def _color_op_patterns(rgb_str):
    """Builds the (pattern, replacement) list used to recolor stroke/fill color operators."""
    num = r'[+-]?\d*\.?\d+'

    def op_pattern(op, n_operands):
        operands = r'\s+'.join([num] * n_operands)
        # require operands not glued to a preceding alnum, and op not glued to a following letter
        return re.compile(r'(?<![A-Za-z0-9.])' + operands + r'\s+' + re.escape(op) + r'(?![A-Za-z])')

    return [
        (op_pattern('RG', 3), f'{rgb_str} RG'),   # stroke RGB
        (op_pattern('rg', 3), f'{rgb_str} rg'),   # fill RGB
        (op_pattern('G', 1),  f'{rgb_str} RG'),   # stroke gray
        (op_pattern('g', 1),  f'{rgb_str} rg'),   # fill gray
        (op_pattern('K', 4),  f'{rgb_str} RG'),   # stroke CMYK
        (op_pattern('k', 4),  f'{rgb_str} rg'),   # fill CMYK
    ]


def _recolor_text_stream(text_stream, rgb_str):
    """Applies all color-operator substitutions to a single decoded content stream.
    Returns (new_text_stream, total_replacement_count)."""
    total = 0
    for pattern, replacement in _color_op_patterns(rgb_str):
        text_stream, n = pattern.subn(replacement, text_stream)
        total += n
    return text_stream, total


def recolor_vector_page(page, debug=False):
    """Replaces vector stroke/fill color operators in the page's own content stream
    AND in every Form XObject used anywhere in the document (CAD/Revit exports commonly
    nest their actual line-drawing geometry inside Form XObjects, not the page stream)."""
    r, g, b = FLOAT_LINE_COLOR
    rgb_str = f"{r:.3f} {g:.3f} {b:.3f}"
    doc = page.parent

    # --- 1. Recolor the page's own content stream ---
    page.clean_contents()
    content_list = page.get_contents()
    page_replacements = 0
    if content_list:
        xref = content_list[0]
        stream_bytes = doc.xref_stream(xref)
        if stream_bytes:
            text_stream = stream_bytes.decode("latin1", errors="ignore")
            text_stream, page_replacements = _recolor_text_stream(text_stream, rgb_str)
            doc.update_stream(xref, text_stream.encode("latin1"))
    elif debug:
        st.sidebar.error("No content streams found on this page.")

    # --- 2. Recolor every Form XObject in the document ---
    # Form XObjects (Subtype == /Form) hold their own independent content streams and
    # are excluded from images/fonts by checking Subtype explicitly, so this is safe.
    xobject_replacements = 0
    xobjects_touched = 0
    for xref in range(1, doc.xref_length()):
        try:
            _, subtype_val = doc.xref_get_key(xref, "Subtype")
        except Exception:
            continue
        if subtype_val != "/Form":
            continue
        try:
            stream_bytes = doc.xref_stream(xref)
        except Exception:
            stream_bytes = None
        if not stream_bytes:
            continue
        text_stream = stream_bytes.decode("latin1", errors="ignore")
        new_text, n = _recolor_text_stream(text_stream, rgb_str)
        if n > 0:
            doc.update_stream(xref, new_text.encode("latin1"))
            xobject_replacements += n
            xobjects_touched += 1

    if debug:
        st.sidebar.subheader("🛠️ Recolor Debug")
        st.sidebar.write(f"Replacements in page content stream: {page_replacements}")
        st.sidebar.write(f"Form XObjects found with color ops: {xobjects_touched}")
        st.sidebar.write(f"Replacements inside Form XObjects: {xobject_replacements}")

        # Re-read the page stream to confirm the write persisted
        persisted = 0
        content_list = page.get_contents()
        if content_list:
            check_bytes = doc.xref_stream(content_list[0])
            check_text = check_bytes.decode("latin1", errors="ignore")
            persisted = check_text.count(f'{rgb_str} RG') + check_text.count(f'{rgb_str} rg')
        st.sidebar.write(f"Target color occurrences confirmed in page stream after write-back: {persisted}")


def diagnose_stream(page):
    page.clean_contents()
    content_list = page.get_contents()
    if not content_list:
        return Counter()
    xref = content_list[0]
    stream_bytes = page.parent.xref_stream(xref)
    if not stream_bytes:
        return Counter()
    text = stream_bytes.decode("latin1", errors="ignore")
    ops = re.findall(r'(?<=\s)([A-Za-z]{1,3})(?=\s|\n)', text)
    return Counter(op for op in ops if op in
        ['RG', 'rg', 'G', 'g', 'K', 'k', 'SC', 'SCN', 'sc', 'scn', 'CS', 'cs'])


if uploaded_file is not None:
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)

    st.write(f"📄 **Total Pages in Document:** {total_pages}")

    st.subheader("1. Select Pages to Process")
    page_option = st.radio("Page Processing Scope:", ["All Pages", "Specific Pages / Range"])

    selected_indices = list(range(total_pages))

    if page_option == "Specific Pages / Range":
        page_input = st.text_input(
            "Enter page numbers or ranges (e.g., '1, 3, 5-8'):",
            value=f"1-{min(5, total_pages)}"
        )
        parsed_indices = set()
        try:
            parts = [p.strip() for p in page_input.split(",") if p.strip()]
            for part in parts:
                if "-" in part:
                    start, end = part.split("-")
                    parsed_indices.update(range(int(start) - 1, int(end)))
                else:
                    parsed_indices.add(int(part) - 1)
            selected_indices = sorted([i for i in parsed_indices if 0 <= i < total_pages])
            st.success(f"Selected {len(selected_indices)} page(s): {[idx + 1 for idx in selected_indices]}")
        except Exception:
            st.error("Invalid page format. Processing all pages by default.")

    # --- LIVE PREVIEW FEATURE ---
    st.subheader("2. Live Preview")
    preview_page_num = st.number_input("Select page to preview:", min_value=1, max_value=total_pages, value=1, step=1)
    preview_idx = preview_page_num - 1

    col1, col2 = st.columns(2)

    preview_page = doc[preview_idx]

    if engine_mode == "Vector (Native PDF Shapes)":
        op_counts = diagnose_stream(preview_page)
        st.sidebar.subheader("🔍 Stream Diagnostics")
        st.sidebar.write(dict(op_counts) if op_counts else "No color operators found")

    pix_orig = preview_page.get_pixmap(dpi=150)
    orig_img = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
    col1.image(orig_img, caption=f"Original (Page {preview_page_num})", use_container_width=True)

    if engine_mode == "Raster (Image-Based)":
        img_np = np.array(orig_img)
        gray_np = np.array(orig_img.convert("L"))
        drawing_mask = gray_np < threshold

        preview_np = np.full_like(img_np, BG_COLOR)
        preview_np[drawing_mask] = LINE_COLOR
        recolored_preview_img = Image.fromarray(preview_np)
    else:
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc, from_page=preview_idx, to_page=preview_idx)
        temp_page = temp_doc[0]

        recolor_vector_page(temp_page, debug=True)

        # Serialize and reopen: guarantees get_pixmap() parses the fresh, edited bytes
        # rather than any stale in-memory page structure MuPDF may have cached.
        temp_bytes = temp_doc.write()
        temp_doc.close()
        temp_doc = fitz.open(stream=temp_bytes, filetype="pdf")
        temp_page = temp_doc[0]

        reopened_stream = temp_doc.xref_stream(temp_page.get_contents()[0]).decode("latin1", errors="ignore")
        r, g, b = FLOAT_LINE_COLOR
        reopened_count = reopened_stream.count(f'{r:.3f} {g:.3f} {b:.3f} RG')
        st.sidebar.write(f"Target color occurrences in reopened doc's stream: {reopened_count}")

        pix_vec = temp_page.get_pixmap(dpi=150)
        recolored_preview_img = Image.frombytes("RGB", [pix_vec.width, pix_vec.height], pix_vec.samples)

    col2.image(recolored_preview_img, caption=f"Recolored Preview ({engine_mode.split()[0]} Mode)", use_container_width=True)

    # --- PROCESS & DOWNLOAD ---
    st.subheader("3. Export Full Document")
    if st.button("Process & Download PDF"):
        with st.spinner("Processing selected pages..."):

            if engine_mode == "Vector (Native PDF Shapes)":
                output_doc = fitz.open()
                for idx in selected_indices:
                    output_doc.insert_pdf(doc, from_page=idx, to_page=idx)
                    target_page = output_doc[-1]
                    recolor_vector_page(target_page, debug=False)

                output_pdf_bytes = output_doc.write()

            else:
                processed_images = []
                for idx in selected_indices:
                    page = doc[idx]
                    pix = page.get_pixmap(dpi=dpi_setting)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

                    img_np = np.array(img)
                    gray_np = np.array(img.convert("L"))
                    drawing_mask = gray_np < threshold

                    recolored_np = np.full_like(img_np, BG_COLOR)
                    recolored_np[drawing_mask] = LINE_COLOR

                    processed_images.append(Image.fromarray(recolored_np))

                output_pdf_path = "recolored_output.pdf"
                processed_images[0].save(
                    output_pdf_path,
                    save_all=True,
                    append_images=processed_images[1:],
                    resolution=float(dpi_setting)
                )
                with open(output_pdf_path, "rb") as f:
                    output_pdf_bytes = f.read()

            st.success("Processing Complete!")
            st.download_button(
                label="📥 Download Recolored PDF",
                data=output_pdf_bytes,
                file_name=f"recolored_{uploaded_file.name}",
                mime="application/pdf"
            )
