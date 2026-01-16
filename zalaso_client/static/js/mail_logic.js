// Stabil logik för Zalaso Mail
window.Zalaso = {
    markedUids: new Set(),

    async openMail(app, tid, uid, isUnread, folder) {
        app.activeThread = tid;
        if (isUnread && !this.markedUids.has(uid)) {
            this.markedUids.add(uid);
            fetch(`/api/mark_read/${uid}?folder=${folder}`).catch(console.error);
        }
    },

    resizeIframe(obj) {
        try {
            const h = obj.contentWindow.document.body.scrollHeight;
            if(h > 20) obj.style.height = h + 'px';
        } catch(e) {}
    }
};
