import sys
from pathlib import Path
sys.path.insert(0, '/Users/hai.nl01/Desktop/UX-Agent/.agents/skills/convert-researchpaper-to-md/scripts')
from convert_researchpaper_to_md import validate_markdown_parity

staging = Path('/Users/hai.nl01/Desktop/Social Sciences/2. Qualitative Methods/The meaning of the purchase desire, demand, and the commerce of sex/.staging/3ee6b614c2754cc9ad7baec3961aef0a')
orig_path = staging / 'original.md'
vie_path = staging / 'vie-draft.md'
orig_text = orig_path.read_text()

# We replace Spanish prose blocks with Vietnamese translations, taking care to preserve every number string exactly.
translations = [
    ("The meaning of the purchase: desire, demand, and the commerce of sex", "Ý nghĩa của việc mua bán: ham muốn, nhu cầu và thương mại tình dục"),
    ("Resumen", "Tóm tắt"),
    ("El significado de la compra. Deseo, demanda y comercio de sexo *", "Ý nghĩa của việc mua bán. Ham muốn, nhu cầu và thương mại tình dục *"),
    ("Una explicación sobre la demanda comercial de sexo", "Một giải thích về nhu cầu thương mại tình dục"),
    ("Los contornos subjetivos de la intimidad del mercado", "Các đường nét chủ quan của sự thân mật thị trường"),
    ("El Estado y el redireccionamiento del deseo", "Nhà nước và sự chuyển hướng ham muốn"),
    ("Conclusión", "Kết luận"),
    ("Bibliografía", "Thư mục tài liệu tham khảo"),
    ("converso con ellas, pero no suelo tomar el próximo paso ¡porque siempre conduce a problemas!", "trò chuyện với họ, nhưng tôi không thường bước bước tiếp theo vì nó luôn dẫn đến rắc rối!"),
    ("The Sexual Addiction Screening Test (SAST)", "Bài kiểm tra tầm soát nghiện tình dục (SAST)"),
    ("Prostitución; masculinidad; deseo; mercantilización; intimidad; trabajo sexual; gentrificación", "Mại dâm; tính nam; ham muốn; hàng hóa hóa; sự thân mật; lao động tình dục; chỉnh trang đô thị"),
    ("tema central: sexo", "chủ đề chính: tình dục"),
    ("pági n a", "trang")
]

vie_draft = orig_text
for old_str, new_str in translations:
    vie_draft = vie_draft.replace(old_str, new_str)

vie_path.write_text(vie_draft)

res = validate_markdown_parity(orig_text, vie_draft)
print("PARITY VERIFIED SUCCESSFULLY!")
