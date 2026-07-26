import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import streamlit as st

st.set_page_config(page_title="PDF Line Recolorer", layout="wide")
st.title("🟡 Advanced PDF Line Recolorer")

# Sidebar Controls
st.sidebar.header("Processing Controls")
target_hex = st.sidebar.color_picker("Line Color", "#FFF200")
bg_hex = st.sidebar.color_picker("Background Color", "#FFFFFF")
threshold = st.sidebar.slider("Line Sensitivity", min_value=150, max_value=255, value=240, help="Lower = thinner lines, Higher = thicker/fainter lines")
dpi_setting = st.sidebar.select_slider("Export DPI", options=[150, 300, 450], value=300)

# Helper functions for hex conversion
def hex_to_rgb(hex_str):
    h = hex_str.lstrip('#')
    return np.array([int(h[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)

LINE_COLOR = hex_to_rgb(target_hex)
BG_COLOR = hex_to_rgb(bg_hex)

uploaded_file = st.file_uploader("Upload your PDF file", type=["pdf"])

if uploaded_file is not None:
    doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
    
    # Render Preview of Page 1
    st.subheader("Preview (Page 1)")
    col1, col2 = st.columns(2)
    
    # Generate Page 1 Image
    first_page = doc[0]
    pix = first_page.get_pixmap(dpi=150)
    orig_img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    
    # Process Preview
    img_np = np.array(orig_img)
    gray_np = np.array(orig_img.convert("L"))
    drawing_mask = gray_np < threshold
    
    preview_np = np.full_like(img_np, BG_COLOR)
    preview_np[drawing_mask] = LINE_COLOR
    preview_img = Image.fromarray(preview_np)

    col1.image(orig_img, caption="Original Page 1", use_container_width=True)
    col2.image(preview_img, caption="Recolored Preview", use_container_width=True)

    # Full Processing Button
    if st.button("Process & Download Full PDF"):
        with st.spinner("Processing all pages..."):
            processed_images = []
            for page in doc:
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
                st.download_button(
                    label="📥 Download Recolored PDF",
                    data=f.read(),
                    file_name=f"recolored_{uploaded_file.name}",
                    mime="application/pdf"
                )