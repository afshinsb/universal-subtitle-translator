const DEMO_MODE = true;

const sampleSrt = `1
00:00:01,000 --> 00:00:03,200
Welcome back to the library.

2
00:00:04,000 --> 00:00:07,500
We found English subtitles next to the movie file.

3
00:00:08,000 --> 00:00:11,000
Now the translation can run without uploading the video.`;

const mockTranslations = {
    Persian: [
        "به کتابخانه خوش برگشتید.",
        "زیرنویس انگلیسی را کنار فایل فیلم پیدا کردیم.",
        "حالا ترجمه بدون آپلود ویدیو اجرا می شود.",
    ],
    Spanish: [
        "Bienvenido de nuevo a la biblioteca.",
        "Encontramos subtitulos en ingles junto al archivo de video.",
        "Ahora la traduccion puede ejecutarse sin subir el video.",
    ],
    French: [
        "Bienvenue dans la bibliotheque.",
        "Nous avons trouve des sous-titres anglais pres du fichier video.",
        "La traduction peut maintenant fonctionner sans televerser la video.",
    ],
    Arabic: [
        "مرحبا بعودتك إلى المكتبة.",
        "وجدنا ترجمة إنجليزية بجانب ملف الفيديو.",
        "يمكن تشغيل الترجمة الآن دون رفع الفيديو.",
    ],
};

const sourceText = document.getElementById("source-text");
const sampleButton = document.getElementById("sample-button");
const translationForm = document.getElementById("translation-form");
const translateButton = document.getElementById("translate-button");
const targetLanguage = document.getElementById("target-language");
const progressBar = document.getElementById("progress-bar");
const resultOutput = document.getElementById("result-output");
const resultState = document.getElementById("result-state");
const scanButton = document.getElementById("scan-button");
const scanTable = document.getElementById("scan-table");
const mediaPath = document.getElementById("media-path");

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function buildTranslatedSrt(language) {
    const lines = mockTranslations[language] || mockTranslations.Persian;

    return `1
00:00:01,000 --> 00:00:03,200
${lines[0]}

2
00:00:04,000 --> 00:00:07,500
${lines[1]}

3
00:00:08,000 --> 00:00:11,000
${lines[2]}`;
}

sampleButton.addEventListener("click", () => {
    sourceText.value = sampleSrt;
    resultState.textContent = "Ready";
});

translationForm.addEventListener("submit", async (event) => {
    event.preventDefault();

    if (!DEMO_MODE) {
        return;
    }

    translateButton.disabled = true;
    translateButton.textContent = "Simulating...";
    resultState.textContent = "Running";
    resultOutput.textContent = "Preparing mock batches...";
    progressBar.style.width = "18%";

    await sleep(450);
    resultOutput.textContent = "Mock provider response received. Repair check passed.";
    progressBar.style.width = "62%";

    await sleep(550);
    resultOutput.textContent = buildTranslatedSrt(targetLanguage.value);
    progressBar.style.width = "100%";
    resultState.textContent = "Done";
    translateButton.disabled = false;
    translateButton.textContent = "Simulate Translation";
});

scanButton.addEventListener("click", async () => {
    scanButton.disabled = true;
    scanButton.textContent = "Scanning...";
    scanTable.innerHTML = `<tr><td colspan="4" class="empty">Scanning ${mediaPath.value || "/media/Movies"} with mock data...</td></tr>`;

    await sleep(650);

    scanTable.innerHTML = [
        {
            video: "Movie.Night.2026.mkv",
            source: "Movie.Night.2026.en.srt",
            status: "Ready",
            output: "Movie.Night.2026.fa.srt",
        },
        {
            video: "Shows/Episode.01.mkv",
            source: "Embedded text subtitle, stream 2",
            status: "Read-only media, output goes to OUTPUT_DIR",
            output: "/app/data/outputs/Shows/Episode.01.fa.srt",
        },
        {
            video: "Shows/Episode.02.mkv",
            source: "No readable subtitle track",
            status: "Skipped",
            output: "-",
        },
    ].map((row) => `
        <tr>
            <td>${row.video}</td>
            <td>${row.source}</td>
            <td>${row.status}</td>
            <td>${row.output}</td>
        </tr>
    `).join("");

    scanButton.disabled = false;
    scanButton.textContent = "Simulate Scan";
});

sourceText.value = sampleSrt;
