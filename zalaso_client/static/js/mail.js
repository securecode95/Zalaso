// Stabil hantering av svara-rutan
const ZalasoMail = {
    initReply(uid, from, subject, base64Body) {
        try {
            // Avkoda den säkra texten
            const decoded = decodeURIComponent(escape(atob(base64Body)));
            const replyArea = document.getElementById('reply-area');
            const replyText = document.getElementById('reply-text');

            // Fyll i svarsrutan
            replyText.value = `\n\n--- ${from} skrev ---\n> ` +
            decoded.substring(0, 500).replace(/\n/g, '\n> ');

            // Visa containern och scrolla ner
            document.getElementById('reply-container').classList.remove('hidden');
            replyArea.scrollIntoView({ behavior: 'smooth' });
            replyText.focus();
        } catch (e) {
            console.error("Kunde inte öppna svara-rutan:", e);
        }
    }
};
