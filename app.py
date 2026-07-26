import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import streamlit as st

st.set_page_config(page_title="PDF Line Recolorer", layout="wide")
st.title("🟡 Advanced PDF Line Recolorer")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Processing Controls")

# Engine Mode Selection
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

# Helper functions for hex conversion
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
        "It preserves 100% vector sharpness, keeps text searchable, and results in tiny file sizes. "
        "*Note: It will not recolor scanned paper documents.*"
    )
else:
    st.info(
        "💡 **Raster Mode Active:** Ideal for scanned paper drawings, images, or flattened PDFs. "
        "It processes every pixel directly to guarantee all drawing lines turn yellow."
    )

uploaded_file = st.file_uploader("Upload your PDF file", type=["pdf"])

if uploaded_file is not None:
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    
    st.write(f"📄 **Total Pages in Document:** {total_pages}")
    
    # --- PAGE SELECTION FEATURE ---
    st.subheader("1. Select Pages to Process")
    page_option = st.radio("Page Processing Scope:", ["All Pages", "Specific Pages / Range"])
    
    selected_indices = list(range(total_pages))  # Default: all pages
    
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
            st.error("Invalid page format. Please enter numbers like '1, 3-5'. Processing all pages by default.")

    # --- LIVE PREVIEW FEATURE ---
    st.subheader("2. Live Preview")
    preview_page_num = st.number_input("Select page to preview:", min_value=1, max_value=total_pages, value=1, step=1)
    preview_idx = preview_page_num - 1

    col1, col2 = st.columns(2)

    # Generate Original Preview Image
    preview_page = doc[preview_idx]
    pix_orig = preview_page.get_pixmap(dpi=150)
    orig_img = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
    col1.image(orig_img, caption=f"Original (Page {preview_page_num})", use_container_width=True)

    # Generate Modified Preview Image depending on Engine
    if engine_mode == "Raster (Image-Based)":
        img_np = np.array(orig_img)
        gray_np = np.array(orig_img.convert("L"))
        drawing_mask = gray_np < threshold
        
        preview_np = np.full_like(img_np, BG_COLOR)
        preview_np[drawing_mask] = LINE_COLOR
        recolored_preview_img = Image.fromarray(preview_np)
    else:
        # Vector mode preview: Create a temporary doc for single page preview
        temp_doc = fitz.open()
        temp_doc.insert_pdf(doc, from_page=preview_idx, to_page=preview_idx)
        temp_page = temp_doc[0]
        
        for shape in temp_page.get_drawings():
            if "color" in shape and shape["color"] is not None:
                shape["color"] = FLOAT_LINE_COLOR
            if "fill" in shape and shape["fill"] is not None:
                shape["fill"] = FLOAT_LINE_COLOR
                
        pix_vec = temp_page.get_pixmap(dpi=150)
        recolored_preview_img = Image.frombytes("RGB", [pix_vec.width, pix_vec.height], pix_vec.samples)

    col2.image(recolored_preview_img, caption=f"Recolored Preview ({engine_mode.split()[0]} Mode)", use_container_width=True)

    # --- PROCESS & DOWNLOAD ---
    st.subheader("3. Export Full Document")
    if st.button("Process & Download PDF"):
        with st.spinner("Processing selected pages..."):
            
            # ENGINE 1: VECTOR PROCESSING
            if engine_mode == "Vector (Native PDF Shapes)":
                output_doc = fitz.open()
                for idx in selected_indices:
                    page = doc[idx]
                    shape_list = page.get_drawings()
                    for shape in shape_list:
                        if "color" in shape and shape["color"] is not None:
                            shape["color"] = FLOAT_LINE_COLOR
                        if "fill" in shape and shape["fill"] is not None:
                            shape["fill"] = FLOAT_LINE_COLOR
                    output_doc.insert_pdf(doc, from_page=idx, to_page=idx)
                
                output_pdf_bytes = output_doc.write()
                
            # ENGINE 2: RASTER PROCESSING
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