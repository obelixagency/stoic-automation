# رفع المشروع على GitHub — خطوة بخطوة

## 1) اعمل الـ repo
1. روح على github.com وسجل دخول.
2. اضغط **New repository**.
3. اسم الـ repo: أي اسم إنجليزي (مثلاً `stoic-automation`). خليه **Private**.
4. متعملش أي تهيئة تانية (من غير README، من غير gitignore) — كله موجود جاهز هنا.
5. اضغط **Create repository**.

## 2) ارفع الملفات
في صفحة الـ repo الفاضي، GitHub هيوريك أوامر زي دي. افتح Terminal (أو Git Bash على ويندوز)
جوه الفولدر اللي فككت فيه الـ zip، واكتب:

```
git init
git add .
git commit -m "initial upload"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO-NAME.git
git push -u origin main
```

غيّر `USERNAME/REPO-NAME` بالاسم بتاعك. لو طلب منك تسجيل دخول، استخدم
Personal Access Token بدل الباسورد العادي (GitHub بيطلب كده دلوقتي):
Settings → Developer settings → Personal access tokens → Generate new token
(اختار صلاحية `repo` بس).

## 3) فعّل GitHub Actions
Actions تلقائيًا شغالة بمجرد الرفع. روح لتاب **Actions** فوق في الـ repo
وهتلاقي اسمين: `Watchdog` و `Prepare voice audio`. متشغّلهمش دلوقتي —
لسه محتاجين نحط الـ Secrets الأول (خطوة جاية).

## 4) حط تاريخ الإطلاق
Settings → Secrets and variables → Actions → تاب **Variables** → New repository variable:
- Name: `LAUNCH_DATE`
- Value: التاريخ اللي هنبدأ ننشر فيه، بالشكل ده `2026-10-06`

## 5) الـ Secrets (التوكنات) — هنحطهم لما نربط كل حساب
Settings → Secrets and variables → Actions → تاب **Secrets** → New repository secret.
الأسماء اللي النظام مستنيها (من غير ما تحطهم دلوقتي، المراقب هيشتغل ويقول
"مش متربط" بس، ومش هيبعت تنبيه غلط):

| Secret | من فين |
|---|---|
| `FB_PAGE_ID`, `FB_PAGE_TOKEN` | حساب فيسبوك المطور + الصفحة |
| `IG_USER_ID` | حساب إنستجرام مربوط بالصفحة |
| `YT_REFRESH_TOKEN`, `YT_CHANNEL_ID` | Google Cloud + قناة يوتيوب |
| `TIKTOK_REFRESH_TOKEN` | تطبيق تيك توك (مسودات بس لحد ما يوافقوا) |
| `PEXELS_API_KEY` | حساب Pexels (مجاني) — للخلفيات |

## بعد الرفع
ابعتلي تأكيد إن الرفع تم، وهنكمل مع بعض: نشغّل workflow الصوت مرة واحدة
(بيحتاج ساعة أو اتنين لإنه يخلص لوحده)، وبعدين نبدأ نربط الحسابات واحد واحد.
