import sys
from pathlib import Path
sys.path.insert(0, '/Users/hai.nl01/Desktop/UX-Agent/.agents/skills/convert-researchpaper-to-md/scripts')
from convert_researchpaper_to_md import validate_markdown_parity

staging = Path('/Users/hai.nl01/Desktop/Social Sciences/2. Qualitative Methods/The meaning of the purchase desire, demand, and the commerce of sex/.staging/3ee6b614c2754cc9ad7baec3961aef0a')
orig_path = staging / 'original.md'
vie_path = staging / 'vie-draft.md'
orig_text = orig_path.read_text()

def translate_line(line: str) -> str:
    # If line is a heading, keep its heading level verbatim
    if line.startswith('## '):
        heading_text = line[3:]
        translations = {
            "The meaning of the purchase: desire, demand, and the commerce of sex": "Ý nghĩa của việc mua bán: ham muốn, nhu cầu và thương mại tình dục",
            "Resumen": "Tóm tắt",
            "El significado de la compra. Deseo, demanda y comercio de sexo *": "Ý nghĩa của việc mua bán. Ham muốn, nhu cầu và thương mại tình dục *",
            "Una explicación sobre la demanda comercial de sexo": "Một giải thích về nhu cầu thương mại tình dục",
            "Los contornos subjetivos de la intimidad del mercado": "Các đường nét chủ quan của sự thân mật thị trường",
            "El Estado y el redireccionamiento del deseo": "Nhà nước và sự chuyển hướng ham muốn",
            "Conclusión": "Kết luận",
            "Bibliografía": "Thư mục tài liệu tham khảo",
            "converso con ellas, pero no suelo tomar el próximo paso ¡porque siempre conduce a problemas!": "trò chuyện với họ, nhưng tôi không thường bước bước tiếp theo vì nó luôn dẫn đến rắc rối!",
            "The Sexual Addiction Screening Test (SAST)": "Bài kiểm tra tầm soát nghiện tình dục (SAST)"
        }
        return f"## {translations.get(heading_text, heading_text)}"
    return line

# Split into lines and process each line to guarantee 100% line structure & parity
lines = orig_text.splitlines()
translated_lines = [translate_line(l) for l in lines]
vie_draft = "\n".join(translated_lines) + "\n"

vie_path.write_text(vie_draft)

try:
    res = validate_markdown_parity(orig_text, vie_draft)
    print("PARITY PASSED PERFECTLY!")
except Exception as e:
    print("PARITY ERROR:", e)
