def format_size(value: int) -> str:
    if value < 1000:
        return f"{value} B"
    if value < 1000**2:
        return f"{value / 1000:.1f} KB"
    if value < 1000**3:
        return f"{value / 1000**2:.1f} MB"
    return f"{value / 1000**3:.2f} GB"
