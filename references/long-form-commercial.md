# סרטון פרסומי/הדרכתי ארוך (120–180 שניות): המתכון המלא

מדריך הפעלה לסרטון של כ־150 שניות עם קריינות AI, מוזיקה בשני חלקים, אפקטים קוליים, 30–45 שוטים מג׳ונרטים, דמות עקבית, כתוביות בעברית עם צבעי מותג, אנימציית לוגו/מעברון וייצוא 1080p ל־WhatsApp. כל שלב מצביע על הכלי הקיים בסקיל; שום דבר כאן אינו מאשר הוצאה, וכל ג׳ינרוט עובר את שער `paid-motion` ו־`provider_jobs.py` כרגיל.

## 0. מבנה ותכנון

- בריף, כיוון ו־storyboard כרגיל (SKILL.md). ב־`direction-v1.json` מלאו את `visual_system.style_constraints` בכללי סגנון **חיוביים** (״אור יום רך ואחיד״, ״פלטה נקייה ומעומעמת״, ״קומפוזיציה מרווחת״) ואת `visual_system.exclusions` בשלושה פריטים לכל היותר. שניהם נכנסים לכל בקשת ג׳ינרוט דרך `style_constraints` ו־`avoid` (למודלים אין negative prompt, ומשפט ״אל תראה X״ ארוך מזכיר להם את X; לכן החיובי הוא העיקר והשלילי קצר). אחרי כל שוט מג׳ונרט: `python scripts/antigravity.py check --media SHOT.mp4 --request REQUEST.json --out reviews/SHOT/check.json` שואל את Gemini שאלות סגורות ״האם X נראה?״ לפני הביקורת האנושית. ״clear״ אינו אישור; ״flagged״ הוא סיבה להסתכל.
- חלוקה לזמן: הכתיבו את התסריט לפי **קטעי קריינות** (4–8 קטעים), לא לפי שוטים. כל קטע מקבל השהיה אחריו (`pause_after`), וזה מה שקובע את ״הנשימות״ של הסרטון. 320–350 מילים בעברית = כ־140 שניות דיבור בקצב 2.4 מילים/שנייה; עם השהיות מגיעים ל־150.
- נקודת המפנה המוזיקלית (למשל 0:45) חייבת ליפול על סוף קטע קריינות + ההשהיה שלו, לא באמצע משפט.

## 1. קריינות עם השהיות מבוימות

ל־eleven_v3 אין `<break>`. השהיה מבוימת היא שקט **שאתם מניחים** בין קטעים. התסריט נכתב כקטעים עם `pause_after`, ומרונדר **בבקשה אחת** (ברירת המחדל: 330 מילים נכנסות בבקשה אחת, והטון, האנרגיה והקצב נשארים רציפים):

```powershell
Copy-Item templates/narration-v1.template.json PROJECT/planning/narration-v1.json   # ערכו: segments עם id/text/pause_after
python scripts/narration_plan.py split --script PROJECT/planning/narration-v1.json --out-dir PROJECT/narration/requests-v001
# request-single.json → provider_jobs.py prepare / approve / execute (עבודה אחת), האזנה, ואז:
python scripts/narration_plan.py layout --mode single --script PROJECT/planning/narration-v1.json --jobs PROJECT/jobs --out-dir PROJECT/narration/layout-v001
```

`layout --mode single` חותך את הרינדור בגבולות הקטעים לפי חותמות הזמן של המילים (עם ידיות של 40/100 אלפיות), מניח את ה־`pause_after` בין החתיכות, ומפיק: `mix-tracks.json` (רצועות voice למיקס), `words.json` מאוחד לכתוביות, `end_of_speech_seconds` לתכנון המוזיקה, ולכל קטע גם את הרווח הטבעי שהיה במקור. הדרישה היחידה: הטקסט שרונדר זהה מילה במילה לתסריט (המספרים חייבים להתאים; אחרת שגיאה מפורשת). קטע שלא טוב = רינדור single חדש (כ־2,000 תווים, זול), או `--mode segments` עם הבקשות הנפרדות (`request-<id>.json`, אישור batch) כשרוצים לתקן קטע בודד ומוכנים להאזין לתפר.

## 2. מוזיקה בשני חלקים, SFX ואוטומציית ווליום

- **הארכה, לא הדבקה.** הדרך שמרגישה מולחנת: קטע מתוח מ־Suno (כ־50 שניות), ואז **הארכה** של אותו קליפ מנקודת המעבר עם סגנון חדש: `{"provider":"suno","style":"builds into uplifting, driving strings and piano","instrumental":true,"extend_clip_id":"<clip id>","extend_at_seconds":45}`. ההארכה יורשת סולם וטמפו מהמקור, אז המעבר נולד בשיר. חלופה: שני קטעים מ־musiclib (`--mood=tense --use-case=background`, `--mood=uplifting,inspirational --use-case=climax`) רק אם ה־BPM זהה או ביחס פשוט (האזינו; אין שדה BPM באינדקס). בכל מקרה מניחים riser/whoosh על נקודת המעבר, ובמיקס fade-out לראשון ו־gain_keys לשני.
- **SFX מ־musiclib** (`--source=sfx --query="whoosh"`, `"page turner"`, `"tick"`); אם הספרייה לא מחזירה תוצאה למונח (למשל תקתוק שעון), חפשו במונח אחר (`clock`, `ticking`) או הקליטו/ג׳נרטו נכס ורשמו את מקורו. `audio_finish.py` מסרב לרצועת SFX שקטה.
- **אוטומציית ווליום:** לכל רצועה אפשר `gain_keys` — רשימת `[שניות_מתחילת_הרצועה, dB]` עם אינטרפולציה ליניארית (ב־dB). זה מה שמרים את המוזיקה במעברים ומוריד אותה לפני קריינות, בנוסף ל־ducking האוטומטי. התבנית `templates/mix-long-form.template.json` מראה מיקס שלם של 150 שניות.

```powershell
python scripts/audio_finish.py --spec PROJECT/mix-v001.json --out-dir PROJECT/audio-v001
```

האזינו ל־stems ולמאסטר. `qa.json` נקשר לקובץ הסופי ב־`delivery_qa.py --audio-qa`.

## 3. שלושים עד ארבעים וחמישה שוטים

- **חוזה שוט אחד לכל שוט** ב־`shots-v1.json` (3–5 שניות = 72–120 פריימים ב־24). Grok מקבל משך שלם בשניות (3, 4, 5).
- **עקביות דמות:** שתי דרכים, ובוחרים לפי השוט:
  1. דמות מדברת: ספריית HeyGen (`character_library.py`), אותה גרסת look בכל השוטים.
  2. סצנה ב־Grok: או 1080p מפריים ראשון יחיד (סטיל Codex שנוצר עם אותם רפרנסים של הדמות), או 720p עם עד 7 רפרנסים (`reference_image`) של הדמות/הסביבה. 1080p + רפרנסים לא קיים; זו מגבלת המודל, לא של הסקיל. לפריים ראשון מדויק מתוך שוט קודם: `python scripts/studio.py still --source SHOT.mp4 --time 4.9 --out first-frame.png`.
- **פרומפט + כללי סגנון:** בכל בקשה `"style_constraints": [...]` מ־`visual_system.style_constraints` ו־`"avoid": [...]` (עד 3) מ־`visual_system.exclusions`. הפרומפט נשאר באנגלית, עם פעולה נראית, תנועת מצלמה ורציפות (ראו providers.md). אחרי איסוף: `antigravity.py check --request` על כל שוט.
- **דמות עקבית = דף דמות לפני הכל.** `templates/character-sheet-v1.template.json`: זהות נראית (פנים, שיער, לבוש, תאורה), ארבע תצוגות שמג׳נרטים ב־Codex ומאשרים בהשוואה זו לצד זו. משם כל שוט הוא **סטיל Codex** עם התצוגות המאושרות כרפרנסים + פרומפט הסצנה, ואז **Grok 1080p מפריים ראשון יחיד**. העקביות באה מהסטילס, ששם השליטה טובה. שוט שממשיך תנועה משוט קודם: 720p עם רפרנסים + הפריים האחרון (`studio.py still`) ואז Magnific ל־1080p במצב שומר עור. בלי ESRGAN ובלי face-restore על פנים (הלקח מתניא). דיבור למצלמה: HeyGen מהתצוגה הקדמית. פיילוט: שלושה שוטים בשלוש סביבות לפני הסדרה.
- **אישור אחד לכל הסדרה, עם פיילוט:** אחרי `prepare` לכל השוטים:

```powershell
python scripts/provider_jobs.py approve-batch --jobs PROJECT/jobs --job ID1 --job ID2 ... --evidence "אישור המשתמש: 36 שוטים, עד 40 ניסיונות Grok" --limit 40 --unit "subscription attempts" --per-job 2 --pilot 3
python scripts/provider_jobs.py batch-status --jobs PROJECT/jobs --batch BATCH_ID
# שלושת הראשונים רצים; צופים, משווים לדף הדמות, ואז:
python scripts/provider_jobs.py batch-release --jobs PROJECT/jobs --batch BATCH_ID --evidence "הפיילוט אושר: פנים/לבוש/אור תואמים; שוט 2 קיבל פרומפט מתוקן"
```

`execute` של כל שוט בודק את הסך המצטבר של ה־batch לפני שליחה; חריגה נחסמת בלי לשלוח, ושוט מחוץ לפיילוט נחסם עד `batch-release`. הניסיון החוזר על שוט שנכשל הוא עדיין החלטה מפורשת (מכסה ב־`--per-job`). `batch-status` מראה מה נשלח, מה נותר ואם הפיילוט שוחרר.

- **בקרת תנועה:** ב־Grok היא טקסט בפרומפט (״slow push-in״, ״slow lateral pan, camera settles״). בהרכבה יש שכבה שנייה של תנועה מבוקרת (סעיף 5).

## 4. כתוביות, טיפוגרפיה ולוגו

- `captions.py` על ה־`words.json` המאוחד מ־`layout`. בקובץ הסגנון: `highlight_color` (צבע המילה המדוברת, או `null` לביטול הקריוקי) ו־`brand_words` — מילון מילה→hex למילים שתמיד מופיעות בצבע המותג (`{"מחוברים": "#1E88E5"}`). התאמה מתעלמת מפיסוק מסביב למילה. הפונטים מ־`<fonts-library>`, RTL דרך Chromium, PNG ל־Blender ול־Resolve (לא Text+).
- לוגו ואייקונים: PNG שקוף כ־`kind:image` עם `fade_in`/`fade_out` ו־`motion` (`fade-rise`, `slide-left`, `slide-right`, `slide-down`, `zoom-in`). SVG לא נתמך; מרנדרים ל־PNG בגודל היעד.
- **מעברון מונפש (פרפר) / לוגו מונפש:** נכס עם אלפא (MOV ProRes 4444 מ־Grok+חילוץ, מ־Blender, או מ־Tesseract) →

```powershell
python scripts/studio.py alpha-sequence --source assets/butterfly.mov --out-dir assets/butterfly-seq   # PNG עם אלפא ל־Blender
python scripts/studio.py alpha-movie --first assets/butterfly-seq/frame_00001.png --fps 24 --out assets/butterfly-resolve.mov   # עותק ל־Resolve
```

בתוכנית: `{"kind":"image-sequence","path":"assets/butterfly-seq/frame_00001.png","duration":36,"hold_last":true,"resolve_movie":"assets/butterfly-resolve.mov"}`. ב־Blender זה רצף PNG; ב־Resolve ה־bridge מחליף אותו אוטומטית ב־MOV.

## 5. UI מרחף, מסך בטלפון, הולוגרמה

- **UI מרחף ליד הדמות:** שכבת PNG/רצף־PNG על ערוץ משלה עם `opacity`, `fade_in` ו־`motion: slide-left` או `transform_keys` (ראו 6). זה קומפוזיטינג 2D; אין הולוגרמה תלת־ממדית אוטומטית. לוק ״הולוגרפי״ מגיע מהעיצוב של ה־PNG עצמו (שקיפות חלקית, קצוות מוארים).
- **מסך בטלפון/טאבלט ביד:** `campaign_techniques.py` עם `planar-screen-replacement` — ארבע פינות לפריים הראשון והאחרון (ואמצע אם היד זזה), הכלי מבצע אינטרפולציה. אין מעקב אוטומטי ואין occlusion אוטומטי; לשוטים של 3–5 שניות עם יד יציבה זה מספיק. אם דרוש מעקב אמיתי: ב־Resolve בתחנה, Fusion Planar Tracker דרך ה־MCP הקהילתי (`timeline_item_fusion`), ואז ה־PNG של המסך מורכב שם. הסקיל לא מחווט את זה אוטומטית; זו עבודה ידנית מודרכת.
- שוטים שנוצרו ב־Grok עם מסך ״ריק״ (טלפון עם מסך אפור אחיד בפרומפט) קלים בהרבה להחלפה.

## 6. תנועת מצלמה בהרכבה

בתוכנית Timeline JSON v1, לכל רצועה חזותית:

| מה רוצים | שדה |
|---|---|
| Slow zoom-in / zoom-out | `"motion": "zoom-in"` או `"zoom-out"`, `"motion_amount": 0.06` (ברירת מחדל; 0.03 עדין, 0.1 בולט) |
| Pan | `"motion": "pan-left"` / `"pan-right"` — הסקיל מגדיל מעט את התמונה כדי שלא ייחשפו שוליים ומזיז לאורך כל הרצועה |
| כניסת אלמנט | `"motion": "slide-left"` / `"slide-right"` / `"slide-down"` / `"fade-rise"` (מתיישב תוך `fade_in` פריימים, או 0.4 שנייה) |
| Freeze frame | `studio.py still --source SHOT.mp4 --time T --out freeze.png` ואז `kind:image` שמתחיל בפריים שאחרי סוף רצועת הווידאו |
| Orbit | רק על מודל תלת־ממד (`shot_templates.py` product-stage / `premium_product.py`); על פוטג׳ שטוח אין orbit אמיתי, מבקשים אותו מ־Grok בפרומפט |
| מסלול מדויק | `"transform_keys": [{"frame":0,"scale":1},{"frame":95,"scale":1.15,"offset_x":-40,"rotation":1.5}]` — פריים יחסי לרצועה, scale מכפיל את הגודל המותאם, offset בפיקסלים של הפלט, rotation במעלות |

התנועות האלו נשמרות ב־`.blend` כקיפריימים רגילים ואפשר לערוך אותן ידנית. ב־hand-off ל־Resolve הן מופיעות ברשימת `unmapped` עם ההנחיה איך לבנות אותן שם. `studio.py validate` מזהיר כשמקור קטן מציר הזמן (למשל 720p מ־Grok ב־1080p) מקבל zoom/pan, כשיותר מ־60% מהרצועות זזות, וכששני preset זהים רצים ברצף. אזהרה, לא חסימה: תנועה בפרומפט של המחולל תמיד עדיפה על תנועה בהרכבה של קליפ קטן.

## 7. הרכבה, גימור וייצוא

- `studio.py validate` → `studio.py assemble --render` (Blender) או `davinci_bridge.py export-xml/import` (Resolve בתחנה). ל־150 שניות ב־1080p24 = 3600 פריימים; רינדור VSE בלפטופ הוא דקות, ב־Resolve על ה־A5000 מהיר יותר.
- `delivery_qa.py --video ... --plan ... --audio-qa PROJECT/audio-v001/qa.json`.
- **WhatsApp:** ברירת המחדל של `whatsapp_delivery.py compress` היא 15MiB, שב־150 שניות זה כ־800kbps — רך מדי ל־720p. השתמשו ב־`--max-mib 40` (כ־2.2Mbps) או `--max-edge 1920 --max-mib 60` אם רוצים 1080p; הדוח כולל `total_kbps` ו־`quality_note` כשהעותק דליל. המאסטר תמיד נשמר.

## מה עדיין ידני, בכוונה

- בחירת takes של קריינות, נקודות חיתוך מוזיקליות, זהות ה־SFX וסנכרון פולי — בהאזנה. התאמת צבע בין מקורות (Grok/HeyGen/Codex): shot-match ב־Resolve בתחנה, או `grade` ידני ב־EDL; אין עדיין מדידה אוטומטית.
- הצבת ארבע פינות למסך טלפון; מעקב אוטומטי רק ב־Fusion.
- ביקורת כל שוט ב־`review_shot.py` ותצפית ברצף המלא עם קול. batch approval חוסך 35 אישורים, לא 35 צפיות.
