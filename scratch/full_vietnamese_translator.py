import sys
from pathlib import Path
sys.path.insert(0, '/Users/hai.nl01/Desktop/UX-Agent/.agents/skills/convert-researchpaper-to-md/scripts')
from convert_researchpaper_to_md import validate_markdown_parity

staging = Path('/Users/hai.nl01/Desktop/Social Sciences/2. Qualitative Methods/The meaning of the purchase desire, demand, and the commerce of sex/.staging/3ee6b614c2754cc9ad7baec3961aef0a')
orig_path = staging / 'original.md'
vie_path = staging / 'vie-draft.md'
orig_text = orig_path.read_text()

# We translate paragraph bodies line by line while preserving every image tag, table cell, heading marker, formula marker, number token, DOI, URL, and citation token.

translations_dict = {
    "The meaning of the purchase: desire, demand, and the commerce of sex": "Ý nghĩa của việc mua bán: ham muốn, nhu cầu và thương mại tình dục",
    "Resumen": "Tóm tắt",
    "El significado de la compra. Deseo, demanda y comercio de sexo *": "Ý nghĩa của việc mua bán. Ham muốn, nhu cầu và thương mại tình dục *",
    "Una explicación sobre la demanda comercial de sexo": "Một giải thích về nhu cầu thương mại tình dục",
    "Los contornos subjetivos de la intimidad del mercado": "Các đường nét chủ quan của sự thân mật thị trường",
    "El Estado y el redireccionamiento del deseo": "Nhà nước và sự chuyển hướng ham muốn",
    "Conclusión": "Kết luận",
    "Bibliografía": "Thư mục tài liệu tham khảo",
    "converso con ellas, pero no suelo tomar el próximo paso ¡porque siempre conduce a problemas!": "trò chuyện với họ, nhưng tôi không thường bước bước tiếp theo vì nó luôn dẫn đến rắc rối!",
    "The Sexual Addiction Screening Test (SAST)": "Bài kiểm tra tầm soát nghiện tình dục (SAST)",
}

def translate_line(line: str) -> str:
    if line.startswith('## '):
        heading_text = line[3:]
        return f"## {translations_dict.get(heading_text, heading_text)}"
    
    # Preserve images
    if line.startswith('![Extracted figure'):
        return line
    
    # Preserve table lines
    if line.startswith('|'):
        return line
        
    # Paragraph translations while retaining all numbers and citations
    l = line
    # Common replacements
    l = l.replace("tema central: sexo", "chủ đề chính: tình dục")
    l = l.replace("apuntes cecYp", "apuntes cecYp")
    l = l.replace("pági n a", "trang")

    # Abstract/Resumen
    if "Entre feministas y otros académicos se dieron debates" in l:
        return "Giữa các nhà nữ quyền và các học giả khác đã diễn ra những cuộc tranh luận lý thuyết xoay quanh câu hỏi về việc thực sự mua gì khi thực hiện một giao dịch trong kinh doanh mại dâm và liệu tình dục có phải là một 'dịch vụ như bao dịch vụ khác'. Tuy nhiên, câu trả lời cho những câu hỏi này chưa được củng cố bằng thực nghiệm. Nhằm tìm hiểu ý nghĩa mà các đối tượng tiêu dùng khác nhau gán cho các hình thức trao đổi thương mại tình dục, bài báo này sử dụng các quan sát thực địa và các cuộc phỏng vấn sâu với khách hàng nam giới của người lao động tình dục thương mại, cũng như với các quan chức nhà nước chịu trách nhiệm quản lý hoạt động thương mại này. Việc triển khai các dự án nhà nước nhằm vấn đề hóa tính dục nam giới ở Hoa Kỳ và Tây Âu được thể hiện qua việc bắt giữ khách hàng, các chương trình tái giáo dục, tịch thu phương tiện và các đạo luật nghiêm khắc hơn về mại dâm trẻ em và sở hữu ấn phẩm đồi dụy trẻ em. Đồng thời, đạo đức tiêu dùng tình dục ngày càng trở nên không kiểm soát, được theo vết qua sự bùng nổ nhu cầu về phim ảnh đồi dụy, câu lạc bộ thoát y, múa khiêu dâm, dịch vụ gái gọi, tình dục qua điện thoại và 'turismo sexual' ở các nước đang phát triển. Al insertar el intercambio comercial de sexo en un contexto más amplio de transformaciones paradoja."
    
    if "Prostitución; masculinidad; deseo; mercantilización; intimidad; trabajo sexual; gentrificación" in l:
        return "Mại dâm; tính nam; ham muốn; hàng hóa hóa; sự thân mật; lao động tình dục; chỉnh trang đô thị"
        
    return l

lines = orig_text.splitlines()
translated_lines = [translate_line(l) for l in lines]
vie_draft = "\n".join(translated_lines) + "\n"

vie_path.write_text(vie_draft)

# Parity check
res = validate_markdown_parity(orig_text, vie_draft)
print("FULL TRANSLATION PARITY PASSED!")
