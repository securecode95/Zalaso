// Hantera högerklick och knappar
const MailActions = {
    markAsRead(uid, folder) {
        fetch(`/api/mark/read/${uid}?folder=${folder}`).then(() => window.location.reload());
    },
    markAsUnread(uid, folder) {
        fetch(`/api/mark/unread/${uid}?folder=${folder}`).then(() => window.location.reload());
    },
    deleteMail(uid, folder) {
        if(confirm('Vill du radera mejlet?')) {
            fetch(`/api/delete/${uid}?folder=${folder}`).then(() => window.location.reload());
        }
    }
};

// Svara-funktion längst ner i tråden
function setupReply(uid, from) {
    const rawText = document.getElementById(`raw-${uid}`).textContent;
    const textArea = document.getElementById('reply-text');
    textArea.value = `\n\n--- ${from} skrev ---\n> ` + rawText.substring(0, 500).replace(/\n/g, '\n> ');
    document.getElementById('reply-container').classList.remove('hidden');
    textArea.focus();
}
