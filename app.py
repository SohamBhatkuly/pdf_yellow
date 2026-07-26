import fitz  # PyMuPDF
import numpy as np
from PIL import Image
import streamlit as st

# Set up page title
st.set_page_config(page_title="PDF Line Recolorer", layout="centered")
st.title("🟡 PDF Line Recolorer")
st.write("Upload a PDF to turn all drawing lines into `#FFF200` yellow with a clean white background.")

# File Uploader
uploaded_file = st.file_uploader("Upload your PDF file", type=["pdf"])

if uploaded_file is not None:
    # Colorpicker & DPI options for future customization/updates
    target_hex = st.color_picker("Choose Line Color", "#FFF200")
    
    # Convert HEX to RGB tuple
    hex_clean = target_hex.lstrip('#')
    rgb_color = np.array([int(hex_clean[i:i+2], 16) for i in (0, 2, 4)], dtype=np.uint8)
    PURE_WHITE = np.array([255, 255, 255], dtype=np.uint8)

    if st.button("Process & Recolor PDF"):
        with st.spinner("Processing pages at crisp 300 DPI..."):
            # Open PDF from bytes
            doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
            processed_images = []

            for page in doc:
                # Render high-res image
                pix = page.get_pixmap(dpi=300)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                
                # NumPy processing
                img_np = np.array(img)
                gray_np = np.array(img.convert("L"))

                # Mask non-white pixels (drawing lines)
                drawing_mask = gray_np < 240

                # Replace with target color
                recolored_np = np.full_like(img_np, PURE_WHITE)
                recolored_np[drawing_mask] = rgb_color

                tinted = Image.fromarray(recolored_np)
                processed_images.append(tinted)

            # Save result to memory
            output_pdf_path = "recolored_output.pdf"
            processed_images[0].save(
                output_pdf_path, 
                save_all=True, 
                append_images=processed_images[1:],
                resolution=300.0
            )

            # Read back for download button
            with open(output_pdf_path, "rb") as f:
                pdf_data = f.read()

            st.success("Complete!")
            st.download_button(
                label="📥 Download Recolored PDF",
                data=pdf_data,
                file_name=f"yellow_{uploaded_file.name}",
                mime="application/pdf"
            )