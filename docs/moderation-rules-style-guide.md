# Moderation Rules Style Guide

This format is recommended when admins publish rules in a message and later import them into the bot.

## Supported rule markers

Each rule should start on a new line with one of:
- `1.`, `2.`, `3.` ...
- `1)`, `2)`, `3)` ...
- keycap emoji markers like `1️⃣`, `2️⃣`, `3️⃣`

## Recommended structure

1. Put each rule marker at the start of its own line.
2. Keep the first sentence concise; it becomes the rule title in UI.
3. Keep extra clarifications in following lines; they are stored as description.
4. Keep all rule text in the message content (not image-only).

## Example

```text
**ПРАВИЛА СЕРВЕРА**

1️⃣ Запрещены угрозы, травля, оскорбления и дискриминация.
Пояснение: уважайте участников и не провоцируйте конфликты.

2️⃣ Запрещён 18+ контент в любом его проявлении.
Пояснение: сюда относятся порнография, нагота и шок-контент.
```

## Notes

- The parser ignores heading lines before the first numbered rule.
- Multi-line text is supported.
- If parsing returns zero rules, review markers and ensure numbers are at line start.
