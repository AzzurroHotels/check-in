import docx
import os

doc_path = "Cloudbeds_PMS_API_Documentation.docx"
if os.path.exists(doc_path):
    doc = docx.Document(doc_path)
    full_text = []
    for para in doc.paragraphs:
        full_text.append(para.text)
    print("\n".join(full_text))
else:
    print("File not found")
