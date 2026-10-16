# סוכן כפול · דף מכירה

דף המכירה של הקורס "סוכן כפול" של שון ופלג (AI Agent School). הגרסה הפעילה: `variations/v3-indigo/`.

## מבנה
- `variations/v3-indigo/index.html`: דף המכירה (קובץ אחד, CSS ו-JS בפנים)
- `variations/v3-indigo/thank-you.html`: עמוד התודה
- `assets/`: וידאו, תמונות, פוסטרים ולוטי שהדף משתמש בהם
- `tools/`: שרת תצוגה, מחולל לוטי, סקריפט בדיקה

## תצוגה מקומית
```
python3 tools/serve.py 8797
```
ואז: http://127.0.0.1:8797/variations/v3-indigo/

השרת תומך ב-Range, כך שהקפיצה בתוך הסרטון עובדת כמו באתר האמיתי.

## לפני עלייה לאוויר
ב-`CONFIG` בראש הסקריפט: `paymentUrl` (Cardcom), `makeWebhook` (Make), `pixelEnabled: true`.
