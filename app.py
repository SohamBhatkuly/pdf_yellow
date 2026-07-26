import fitz  # PyMuPDF
import numpy as np
import cv2
import io
from PIL import Image
import streamlit as st

st.set_page_config(page_title="PDF Line Recolorer", layout="wide")
st.title("🟡 Advanced PDF Line Recolorer Pro")

# --- SIDEBAR CONTROLS ---
st.sidebar.header("Processing Controls")

# Helper functions for hex conversion
def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return np.array([int(h[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)

def hex_to_float_rgb(hex_str):
    h = hex_str.lstrip('#')
    return tuple(int(h[i:i+2], 16) / 255.0 for i in (0, 2, 4))

target_hex = st.sidebar.color_picker("Line Color", "#FFF200")
bg_hex = st.sidebar.color_picker("Background Color (Raster Only)", "#FFFFFF")

LINE_COLOR = hex_to_rgb(target_hex)
BG_COLOR = hex_to_rgb(bg_hex)
FLOAT_LINE_COLOR = hex_to_float_rgb(target_hex)

# --- AUTO-DETECTION HELPER ---
def analyze_pdf_for_engine(doc):
    """Analyzes Page 1 to recommend the best engine."""
    first_page = doc[0]
    drawings = first_page.get_drawings()
    images = first_page.get_images()
    
    if len(drawings) > 20 and len(images) == 0:
        return "Vector (Native PDF Shapes)", "We detected rich vector paths. **Vector Mode** is highly recommended!"
    else:
        return "Raster (Image-Based)", "We detected embedded images/scans. **Raster Mode** is highly recommended!"

# Upload block
uploaded_file = st.file_uploader("Upload your PDF file", type=["pdf"])

if uploaded_file is not None:
    # Read PDF to memory
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    total_pages = len(doc)
    
    # Run Auto-Detection
    recommended_engine, engine_reason = analyze_pdf_for_engine(doc)
    
    st.write(f"📄 **Total Pages in Document:** {total_pages}")
    st.info(f"🔍 **Auto-Detect:** {engine_reason}")

    # Engine Mode Selection
    engine_mode = st.sidebar.radio(
        "Recoloring Engine",
        options=["Raster (Image-Based)", "Vector (Native PDF Shapes)"],
        index=0 if "Raster" in recommended_engine else 1,
        help="Raster: Applies CV2 Adaptive Thresholding. Vector: Redraws native CAD paths."
    )

    if engine_mode == "Raster (Image-Based)":
        dpi_setting = st.sidebar.select_slider("Export DPI", options=[150, 300, 450, 600], value=300)
        cv2_block_size = st.sidebar.slider("Adaptive Block Size", 11, 51, 21, step=2, help="Higher = captures thicker regions")
        cv2_c = st.sidebar.slider("Adaptive Constant (C)", 1, 20, 10, help="Lower = more noise/lines, Higher = cleaner background")

    # --- ADVANCED PAGE SELECTION PARSER ---
    st.subheader("1. Select Pages to Process")
    page_option = st.radio("Page Processing Scope:", ["All Pages", "Specific Pages / Range"])
    
    selected_indices = list(range(total_pages))  
    
    if page_option == "Specific Pages / Range":
        page_input = st.text_input(
            "Enter pages (e.g., '1, 3, 5-8', 'odd', 'even', 'last', '4-'):",
            value=f"1-{min(5, total_pages)}"
        )
        parsed_indices = set()
        try:
            raw_input = page_input.strip().lower()
            if raw_input == "all":
                parsed_indices.update(range(total_pages))
            elif raw_input == "odd":
                parsed_indices.update(range(0, total_pages, 2))
            elif raw_input == "even":
                parsed_indices.update(range(1, total_pages, 2))
            elif raw_input == "last":
                parsed_indices.add(total_pages - 1)
            else:
                parts = [p.strip() for p in raw_input.split(",") if p.strip()]
                for part in parts:
                    if "-" in part:
                        start, end = part.split("-")
                        start_idx = int(start) - 1 if start else 0
                        end_idx = int(end) - 1 if end else total_pages - 1
                        parsed_indices.update(range(start_idx, end_idx + 1))
                    else:
                        parsed_indices.add(int(part) - 1)
            
            selected_indices = sorted([i for i in parsed_indices if 0 <= i < total_pages])
            st.success(f"Selected {len(selected_indices)} page(s): {[idx + 1 for idx in selected_indices]}")
        except Exception:
            st.error("Invalid page format. Processing all pages by default.")
            selected_indices = list(range(total_pages))

    # --- CORE PROCESSING FUNCTIONS ---
    def process_vector_page(page, output_doc):
        """Draws true vector paths onto a blank page in the output document."""
        out_page = output_doc.new_page(width=page.rect.width, height=page.rect.height)
        shape_canvas = out_page.new_shape()
        
        for p in page.get_drawings():
            for item in p["items"]:
                if item[0] == "l":    # Line
                    shape_canvas.draw_line(item[1], item[2])
                elif item[0] == "c":  # Curve
                    shape_canvas.draw_bezier(item[1], item[2], item[3], item[4])
                elif item[0] == "re": # Rectangle
                    shape_canvas.draw_rect(item[1])
                elif item[0] == "qu": # Quad
                    shape_canvas.draw_quad(item[1])
            
            width = p.get("width", 1.0)
            color = FLOAT_LINE_COLOR if p.get("color") is not None else None
            fill = FLOAT_LINE_COLOR if p.get("fill") is not None else None
            
            shape_canvas.finish(width=width, color=color, fill=fill)
        
        shape_canvas.commit()
        return out_page

    def process_raster_image(img):
        """Applies OpenCV Adaptive Thresholding & Alpha Blending."""
        img_np = np.array(img)
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
        
        # Blur to remove paper dust
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        
        # Adaptive Threshold isolates lines regardless of gradient shadows
        thresh = cv2.adaptiveThreshold(
            blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, cv2_block_size, cv2_c
        )
        
        # Morphological Closing to connect faint segments
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        morphed_mask = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        # Alpha/Darkness calculation to preserve antialiasing
        darkness = 1.0 - (gray / 255.0)  # Shape (H, W)
        darkness_rgb = np.stack([darkness]*3, axis=-1)
        
        # Blend base Background + Line Color based on original pixel darkness
        blended = BG_COLOR * (1 - darkness_rgb) + LINE_COLOR * darkness_rgb
        blended = np.clip(blended, 0, 255).astype(np.uint8)
        
        # Build final image (Apply blended lines where mask == 0, else BG)
        recolored_np = np.full_like(img_np, BG_COLOR)
        line_indices = (morphed_mask < 128)
        recolored_np[line_indices] = blended[line_indices]
        
        return Image.fromarray(recolored_np)

    # --- LIVE PREVIEW FEATURE ---
    st.subheader("2. Live Preview")
    preview_page_num = st.number_input("Select page to preview:", min_value=1, max_value=total_pages, value=selected_indices[0]+1 if selected_indices else 1)
    preview_idx = preview_page_num - 1

    col1, col2 = st.columns(2)
    preview_page = doc[preview_idx]
    
    # Original Image
    pix_orig = preview_page.get_pixmap(dpi=150)
    orig_img = Image.frombytes("RGB", [pix_orig.width, pix_orig.height], pix_orig.samples)
    col1.image(orig_img, caption=f"Original (Page {preview_page_num})", use_container_width=True)

    # Preview Processing
    if engine_mode == "Raster (Image-Based)":
        recolored_preview_img = process_raster_image(orig_img)
    else:
        temp_doc = fitz.open()
        process_vector_page(preview_page, temp_doc)
        pix_vec = temp_doc[0].get_pixmap(dpi=150)
        recolored_preview_img = Image.frombytes("RGB", [pix_vec.width, pix_vec.height], pix_vec.samples)

    col2.image(recolored_preview_img, caption=f"Recolored Preview", use_container_width=True)

    # --- PROCESS & DOWNLOAD ---
    st.subheader("3. Export Full Document")
    if st.button("Process & Download PDF", type="primary"):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        output_pdf_bytes = None
        total_selected = len(selected_indices)
        
        try:
            # ENGINE 1: VECTOR PROCESSING
            if engine_mode == "Vector (Native PDF Shapes)":
                output_doc = fitz.open()
                for i, idx in enumerate(selected_indices):
                    status_text.text(f"Extracting and redrawing vector paths... (Page {i+1} of {total_selected})")
                    process_vector_page(doc[idx], output_doc)
                    progress_bar.progress((i + 1) / total_selected)
                
                output_pdf_bytes = output_doc.write()
            
            # ENGINE 2: RASTER PROCESSING (PURE IN-MEMORY)
            else:
                processed_images = []
                for i, idx in enumerate(selected_indices):
                    status_text.text(f"Applying OpenCV adaptive morphology... (Page {i+1} of {total_selected})")
                    pix = doc[idx].get_pixmap(dpi=dpi_setting)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    
                    processed_img = process_raster_image(img)
                    processed_images.append(processed_img)
                    progress_bar.progress((i + 1) / total_selected)
                
                status_text.text("Compiling images into PDF stream...")
                pdf_io = io.BytesIO()
                processed_images[0].save(
                    pdf_io, 
                    format="PDF",
                    save_all=True, 
                    append_images=processed_images[1:],
                    resolution=float(dpi_setting)
                )
                output_pdf_bytes = pdf_io.getvalue()

            # FINALIZE
            progress_bar.empty()
            status_text.empty()
            st.success("✨ Processing Complete!")
            
            # Size Estimator Fix
            mb_size = len(output_pdf_bytes) / (1024 * 1024)
            st.write(f"📦 **Estimated File Size:** `{mb_size:.2f} MB`")
            
            st.download_button(
                label="📥 Download Recolored PDF",
                data=output_pdf_bytes,
                file_name=f"recolored_{uploaded_file.name}",
                mime="application/pdf"
            )
        except Exception as e:
            st.error(f"An error occurred during processing: {e}")