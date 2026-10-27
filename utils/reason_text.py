from html import escape


def reason_question(applicant_name: str) -> str:
    """👎 bergan a'zodan sabab so'raydigan xabar (voting va /start da bir xil)."""
    return (
        f"Siz <b>{escape(applicant_name)}</b> arizasiga 👎 berdingiz.\n"
        "Qaroringiz sababini qisqacha yozib yuborsangiz, minnatdor bo'lamiz:"
    )
