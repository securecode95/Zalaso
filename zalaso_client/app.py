from flask import Flask, render_template, request, redirect, url_for, Response, session
from imap_tools import MailBox, A
import smtplib, ssl, hashlib, json, os, sys, base64, time, re, html, webbrowser, urllib.parse, socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from datetime import date, timedelta, datetime, timezone
from email.utils import formatdate
import sqlite3
import threading

try:
    from pyngrok import ngrok, conf
except ImportError:
    ngrok = None

def resource_path(relative_path):
    """ Hitta sökväg till resurser, fungerar för dev och PyInstaller """
    try:
        # PyInstaller skapar en temp-mapp och lagrar sökvägen i _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_data_path(filename):
    """ Returnerar sökväg för datafiler (DB, inställningar) som fungerar installerat """
    # 1. Om filen redan finns i nuvarande mapp (Dev mode), använd den
    if os.path.exists(filename):
        return filename
    
    # 2. Om vi körs som .exe (Frozen), använd APPDATA för att undvika rättighetsproblem
    if getattr(sys, 'frozen', False):
        if sys.platform == 'win32':
            base = os.environ.get('APPDATA')
            path = os.path.join(base, 'ZalasoMail')
        else:
            path = os.path.join(os.path.expanduser('~'), '.zalaso_mail')
        if not os.path.exists(path):
            os.makedirs(path)
        return os.path.join(path, filename)
    
    # 3. Fallback till nuvarande mapp
    return filename

app = Flask(__name__, template_folder=resource_path('templates'), static_folder=resource_path('static'))
app.secret_key = 'zalaso_final_stable_v10'
app.permanent_session_lifetime = timedelta(days=31)
SETTINGS_FILE = get_data_path('settings.json')
READ_STATUS_FILE = get_data_path('read_status.json')
STAR_STATUS_FILE = get_data_path('star_status.json')
FOLDER_ICONS_FILE = get_data_path('folder_icons.json')
SPAM_FILTERS_FILE = get_data_path('spam_filters.json')
LOG_FILE = get_data_path('zalaso.log')
log_lock = threading.Lock()

def log_event(message):
    try:
        with log_lock:
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            with open(LOG_FILE, 'a') as f:
                f.write(f"[{timestamp}] {message}\n")
    except: pass

# Fix för Windows GUI-krasch: Omdirigera print till ingenting om ingen konsol finns
if sys.platform == 'win32' and getattr(sys, 'frozen', False):
    class NullWriter:
        def write(self, text): pass
        def flush(self): pass
    sys.stdout = NullWriter()
    sys.stderr = NullWriter()

# Global felhanterare för att visa fel i webbläsaren (viktigt för .exe)
@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    log_event(f"CRITICAL ERROR: {e}\n{traceback.format_exc()}")
    return f"<h1>Ett fel inträffade (Error 500)</h1><pre>{e}\n\n{traceback.format_exc()}</pre>", 500

TRANSLATIONS = {
    'sv': {
        'inbox': 'Inkorg', 'sent': 'Skickat', 'drafts': 'Utkast', 'trash': 'Papperskorg', 'spam': 'Skräppost', 'starred': 'Stjärnmärkt',
        'settings': 'Inställningar', 'logout': 'Logga ut', 'compose': 'Skriv', 'search_placeholder': 'Sök i E-post', 'no_results': 'Inga resultat hittades',
        'folders': 'Mappar', 'my_folders': 'Mina mappar', 'new_folder': 'Ny mapp',
        'delete_folder_confirm': 'Är du säker på att du vill ta bort mappen "{}"? Alla mail i mappen kommer att raderas.',
        'block_sender_confirm': 'Vill du blockera avsändaren "{}"? Alla nuvarande och framtida mail från denna avsändare flyttas till Skräppost.',
        'mark_ad_confirm': 'Vill du markera avsändaren "{}" som reklam? Alla mail från denna avsändare flyttas till Reklam-mappen.',
        'whitelist_sender_confirm': 'Vill du lägga till "{}" som betrodd avsändare? Mail från denna avsändare kommer inte att filtreras som spam eller reklam.',
        'delete_selected_confirm': 'Är du säker på att du vill ta bort alla mail på denna sida?',
        'empty_trash_confirm': 'Är du säker på att du vill tömma papperskorgen? Detta tar bort alla mail permanent.',
        'undo_delete': 'Konversationen har raderats.', 'undo_move': 'Konversationen flyttades.', 'undo': 'Ångra',
        'reply': 'Svara', 'forward': 'Vidarebefordra', 'delete': 'Radera', 'mark_read': 'Markera som läst', 'mark_unread': 'Markera som oläst',
        'move_to': 'Flytta till', 'block_sender': 'Blockera avsändare', 'mark_as_ad': 'Markera som reklam', 'whitelist_sender': 'Betrodd avsändare',
        'general': 'Allmänt', 'connection': 'Anslutning', 'presets': 'Snabbval', 'contacts': 'Kontakter', 'labels': 'Etiketter', 'rules': 'Regler', 'filters': 'Filter', 'logs': 'Logg',
        'save': 'Spara', 'cancel': 'Avbryt', 'email_username': 'Email / Användarnamn', 'password': 'Lösenord',
        'imap_server': 'IMAP Server', 'port': 'Port', 'smtp_server': 'SMTP Server', 'layout': 'Layout', 'normal': 'Normal', 'compact': 'Kompakt',
        'signature': 'Signatur', 'web_password': 'Webb-lösenord (Valfritt)', 'web_password_placeholder': 'Lämna tomt för inget skydd',
        'restart': 'Starta om', 'restart_confirm': 'Är du säker på att du vill starta om servern?',
        'app_password_hint': 'För Gmail/Outlook: Använd App-lösenord om 2FA är aktiverat.',
        'add_contact': 'Lägg till kontakt', 'name': 'Namn', 'email': 'E-post', 'add': 'Lägg till', 'my_contacts': 'Mina kontakter',
        'no_contacts': 'Inga kontakter sparade än.', 'create_label': 'Skapa ny etikett', 'label_name': 'Etikettnamn', 'apply_if': 'Applicera om...',
        'subject': 'Ämne', 'sender': 'Avsändare', 'both': 'Båda', 'keyword_placeholder': 'Nyckelord (t.ex. order, faktura)...',
        'my_labels': 'Mina etiketter', 'no_labels': 'Inga etiketter skapade än.', 'create_rule': 'Skapa ny regel',
        'move_to_folder': '...flytta automatiskt till mappen:', 'select_folder': 'Välj mapp...', 'save_rule': 'Spara regel',
        'active_rules': 'Aktiva regler', 'if_sender': 'Om avsändare:', 'if_subject_sender': 'Om ämne/avsändare:', 'if_subject': 'Om ämne:',
        'no_rules': 'Inga regler skapade än.', 'blocked_senders': 'Blockerade avsändare (Spam)', 'no_blocked': 'Inga blockerade avsändare',
        'ad_senders': 'Reklam-avsändare', 'no_ads': 'Inga reklam-avsändare', 'trusted_senders': 'Betrodda avsändare (Whitelist)',
        'no_trusted': 'Inga betrodda avsändare', 'event_log': 'Händelselogg', 'send_to_support': 'Skicka till support', 'sending': 'Skickar...',
        'update': 'Uppdatera', 'no_logs': 'Inga loggar tillgängliga.', 'new_message': 'Nytt meddelande', 'to': 'Till', 'attach_files': 'Bifoga filer',
        'uploading': 'Laddar upp...', 'send': 'Skicka', 'language': 'Språk', 'swedish': 'Svenska', 'english': 'Engelska', 'polish': 'Polska', 'german': 'Tyska',
        'msgs_in_thread': 'meddelanden i konversationen', 'print': 'Skriv ut', 'empty_trash': 'Töm papperskorgen', 'selected': 'markerade',
        'create_folder': 'Skapa ny mapp', 'folder_name': 'Mappnamn', 'select_icon': 'Välj ikon', 'create': 'Skapa',
        'login': 'Logga in', 'remember_me': 'Kom ihåg mig', 'forgot_password': 'Glömt lösenordet?', 'welcome': 'Välkommen till Zalaso Mail',
        'configure_account': 'Konfigurera ditt e-postkonto för att komma igång', 'your_account': 'Ditt Konto', 'incoming_imap': 'Inkommande (IMAP)',
        'outgoing_smtp': 'Utgående (SMTP)', 'test_connection': 'Testa anslutning', 'save_and_start': 'Spara och Starta', 'testing': 'Testar...',
        'connection_success': '✓ Anslutning lyckades!', 'failed': 'Misslyckades', 'network_error': 'Ett nätverksfel inträffade.',
        'fill_imap': 'Fyll i alla IMAP-fält först.', 'unsaved_changes': 'Du har osparade ändringar.',
        'label_created': 'Etikett skapad! Appliceras på befintliga mail i bakgrunden.', 'log_sent': 'Logg skickad!', 'error': 'Fel',
        'could_not_send': 'Kunde inte skicka', 'could_not_create_folder': 'Kunde inte skapa mapp', 'an_error_occurred': 'Ett fel inträffade.',
        'reply_to': 'Svarar till:', 'forwarding': 'Vidarebefordra', 'forwarded_message': '---------- Vidarebefordrat meddelande ----------', 'wrote': 'skrev', 'reklam': 'Reklam',
        'remote_support': 'Fjärrsupport', 'generate_link': 'Generera länk', 'starting': 'Startar...', 'copy': 'Kopiera', 'stop': 'Avsluta', 'support_hint': 'Ge denna länk till supporten.',
        'ngrok_token_label': 'Ngrok Authtoken', 'ngrok_token_help': 'Krävs. Hämta gratis på dashboard.ngrok.com', 'ngrok_missing': 'Authtoken saknas. Ange den ovan.'
    },
    'en': {
        'inbox': 'Inbox', 'sent': 'Sent', 'drafts': 'Drafts', 'trash': 'Trash', 'spam': 'Spam', 'starred': 'Starred',
        'settings': 'Settings', 'logout': 'Logout', 'compose': 'Compose', 'search_placeholder': 'Search in Mail', 'no_results': 'No results found',
        'folders': 'Folders', 'my_folders': 'My Folders', 'new_folder': 'New Folder',
        'delete_folder_confirm': 'Are you sure you want to delete the folder "{}"? All emails in it will be deleted.',
        'block_sender_confirm': 'Do you want to block sender "{}"? All current and future emails from this sender will be moved to Spam.',
        'mark_ad_confirm': 'Do you want to mark sender "{}" as ad? All emails from this sender will be moved to the Ads folder.',
        'whitelist_sender_confirm': 'Do you want to add "{}" as a trusted sender? Emails from this sender will not be filtered as spam or ads.',
        'delete_selected_confirm': 'Are you sure you want to delete all emails on this page?',
        'empty_trash_confirm': 'Are you sure you want to empty the trash? This will permanently delete all emails.',
        'undo_delete': 'Conversation deleted.', 'undo_move': 'Conversation moved.', 'undo': 'Undo',
        'reply': 'Reply', 'forward': 'Forward', 'delete': 'Delete', 'mark_read': 'Mark as read', 'mark_unread': 'Mark as unread',
        'move_to': 'Move to', 'block_sender': 'Block sender', 'mark_as_ad': 'Mark as ad', 'whitelist_sender': 'Trusted sender',
        'general': 'General', 'connection': 'Connection', 'presets': 'Presets', 'contacts': 'Contacts', 'labels': 'Labels', 'rules': 'Rules', 'filters': 'Filters', 'logs': 'Logs',
        'save': 'Save', 'cancel': 'Cancel', 'email_username': 'Email / Username', 'password': 'Password',
        'imap_server': 'IMAP Server', 'port': 'Port', 'smtp_server': 'SMTP Server', 'layout': 'Layout', 'normal': 'Normal', 'compact': 'Compact',
        'signature': 'Signature', 'web_password': 'Web Password (Optional)', 'web_password_placeholder': 'Leave empty for no protection',
        'restart': 'Restart', 'restart_confirm': 'Are you sure you want to restart the server?',
        'app_password_hint': 'For Gmail/Outlook: Use App Password if 2FA is enabled.',
        'add_contact': 'Add Contact', 'name': 'Name', 'email': 'Email', 'add': 'Add', 'my_contacts': 'My Contacts',
        'no_contacts': 'No contacts saved yet.', 'create_label': 'Create New Label', 'label_name': 'Label Name', 'apply_if': 'Apply if...',
        'subject': 'Subject', 'sender': 'Sender', 'both': 'Both', 'keyword_placeholder': 'Keyword (e.g. order, invoice)...',
        'my_labels': 'My Labels', 'no_labels': 'No labels created yet.', 'create_rule': 'Create New Rule',
        'move_to_folder': '...automatically move to folder:', 'select_folder': 'Select folder...', 'save_rule': 'Save Rule',
        'active_rules': 'Active Rules', 'if_sender': 'If sender:', 'if_subject_sender': 'If subject/sender:', 'if_subject': 'If subject:',
        'no_rules': 'No rules created yet.', 'blocked_senders': 'Blocked Senders (Spam)', 'no_blocked': 'No blocked senders',
        'ad_senders': 'Ad Senders', 'no_ads': 'No ad senders', 'trusted_senders': 'Trusted Senders (Whitelist)',
        'no_trusted': 'No trusted senders', 'event_log': 'Event Log', 'send_to_support': 'Send to Support', 'sending': 'Sending...',
        'update': 'Update', 'no_logs': 'No logs available.', 'new_message': 'New Message', 'to': 'To', 'attach_files': 'Attach files',
        'uploading': 'Uploading...', 'send': 'Send', 'language': 'Language', 'swedish': 'Swedish', 'english': 'English', 'polish': 'Polish', 'german': 'German',
        'msgs_in_thread': 'messages in conversation', 'print': 'Print', 'empty_trash': 'Empty Trash', 'selected': 'selected',
        'create_folder': 'Create New Folder', 'folder_name': 'Folder Name', 'select_icon': 'Select Icon', 'create': 'Create',
        'login': 'Login', 'remember_me': 'Remember me', 'forgot_password': 'Forgot password?', 'welcome': 'Welcome to Zalaso Mail',
        'configure_account': 'Configure your email account to get started', 'your_account': 'Your Account', 'incoming_imap': 'Incoming (IMAP)',
        'outgoing_smtp': 'Outgoing (SMTP)', 'test_connection': 'Test Connection', 'save_and_start': 'Save and Start', 'testing': 'Testing...',
        'connection_success': '✓ Connection successful!', 'failed': 'Failed', 'network_error': 'A network error occurred.',
        'fill_imap': 'Fill in all IMAP fields first.', 'unsaved_changes': 'You have unsaved changes.',
        'label_created': 'Label created! Applying to existing emails in background.', 'log_sent': 'Log sent!', 'error': 'Error',
        'could_not_send': 'Could not send', 'could_not_create_folder': 'Could not create folder', 'an_error_occurred': 'An error occurred.',
        'reply_to': 'Replying to:', 'forwarding': 'Forwarding', 'forwarded_message': '---------- Forwarded message ----------', 'wrote': 'wrote', 'reklam': 'Ads',
        'remote_support': 'Remote Support', 'generate_link': 'Generate Link', 'starting': 'Starting...', 'copy': 'Copy', 'stop': 'Stop', 'support_hint': 'Give this link to support.',
        'ngrok_token_label': 'Ngrok Authtoken', 'ngrok_token_help': 'Required. Get free at dashboard.ngrok.com', 'ngrok_missing': 'Authtoken missing. Enter it above.'
    },
    'pl': {
        'inbox': 'Odebrane', 'sent': 'Wysłane', 'drafts': 'Wersje robocze', 'trash': 'Kosz', 'spam': 'Spam', 'starred': 'Oznaczone gwiazdką',
        'settings': 'Ustawienia', 'logout': 'Wyloguj', 'compose': 'Utwórz', 'search_placeholder': 'Szukaj w poczcie', 'no_results': 'Nie znaleziono wyników',
        'folders': 'Foldery', 'my_folders': 'Moje foldery', 'new_folder': 'Nowy folder',
        'delete_folder_confirm': 'Czy na pewno chcesz usunąć folder "{}"? Wszystkie wiadomości w nim zostaną usunięte.',
        'block_sender_confirm': 'Czy chcesz zablokować nadawcę "{}"? Wszystkie obecne i przyszłe wiadomości od tego nadawcy zostaną przeniesione do spamu.',
        'mark_ad_confirm': 'Czy chcesz oznaczyć nadawcę "{}" jako reklamę? Wszystkie wiadomości od tego nadawcy zostaną przeniesione do folderu Reklamy.',
        'whitelist_sender_confirm': 'Czy chcesz dodać "{}" jako zaufanego nadawcę? Wiadomości od tego nadawcy nie będą filtrowane jako spam ani reklamy.',
        'delete_selected_confirm': 'Czy na pewno chcesz usunąć wszystkie wiadomości na tej stronie?',
        'empty_trash_confirm': 'Czy na pewno chcesz opróżnić kosz? Spowoduje to trwałe usunięcie wszystkich wiadomości.',
        'undo_delete': 'Rozmowa usunięta.', 'undo_move': 'Rozmowa przeniesiona.', 'undo': 'Cofnij',
        'reply': 'Odpowiedz', 'forward': 'Przekaż', 'delete': 'Usuń', 'mark_read': 'Oznacz jako przeczytane', 'mark_unread': 'Oznacz jako nieprzeczytane',
        'move_to': 'Przenieś do', 'block_sender': 'Zablokuj nadawcę', 'mark_as_ad': 'Oznacz jako reklamę', 'whitelist_sender': 'Zaufany nadawca',
        'general': 'Ogólne', 'connection': 'Połączenie', 'presets': 'Presety', 'contacts': 'Kontakty', 'labels': 'Etykiety', 'rules': 'Reguły', 'filters': 'Filtry', 'logs': 'Logi',
        'save': 'Zapisz', 'cancel': 'Anuluj', 'email_username': 'Email / Nazwa użytkownika', 'password': 'Hasło',
        'imap_server': 'Serwer IMAP', 'port': 'Port', 'smtp_server': 'Serwer SMTP', 'layout': 'Układ', 'normal': 'Normalny', 'compact': 'Kompaktowy',
        'signature': 'Podpis', 'web_password': 'Hasło WWW (Opcjonalne)', 'web_password_placeholder': 'Pozostaw puste dla braku ochrony',
        'restart': 'Uruchom ponownie', 'restart_confirm': 'Czy na pewno chcesz ponownie uruchomić serwer?',
        'app_password_hint': 'Dla Gmail/Outlook: Użyj hasła aplikacji, jeśli włączone jest 2FA.',
        'add_contact': 'Dodaj kontakt', 'name': 'Nazwa', 'email': 'Email', 'add': 'Dodaj', 'my_contacts': 'Moje kontakty',
        'no_contacts': 'Brak zapisanych kontaktów.', 'create_label': 'Utwórz nową etykietę', 'label_name': 'Nazwa etykiety', 'apply_if': 'Zastosuj jeśli...',
        'subject': 'Temat', 'sender': 'Nadawca', 'both': 'Oba', 'keyword_placeholder': 'Słowo kluczowe (np. zamówienie, faktura)...',
        'my_labels': 'Moje etykiety', 'no_labels': 'Brak utworzonych etykiet.', 'create_rule': 'Utwórz nową regułę',
        'move_to_folder': '...automatycznie przenieś do folderu:', 'select_folder': 'Wybierz folder...', 'save_rule': 'Zapisz regułę',
        'active_rules': 'Aktywne reguły', 'if_sender': 'Jeśli nadawca:', 'if_subject_sender': 'Jeśli temat/nadawca:', 'if_subject': 'Jeśli temat:',
        'no_rules': 'Brak utworzonych reguł.', 'blocked_senders': 'Zablokowani nadawcy (Spam)', 'no_blocked': 'Brak zablokowanych nadawców',
        'ad_senders': 'Nadawcy reklam', 'no_ads': 'Brak nadawców reklam', 'trusted_senders': 'Zaufani nadawcy (Biała lista)',
        'no_trusted': 'Brak zaufanych nadawców', 'event_log': 'Dziennik zdarzeń', 'send_to_support': 'Wyślij do pomocy technicznej', 'sending': 'Wysyłanie...',
        'update': 'Aktualizuj', 'no_logs': 'Brak dostępnych logów.', 'new_message': 'Nowa wiadomość', 'to': 'Do', 'attach_files': 'Załącz pliki',
        'uploading': 'Przesyłanie...', 'send': 'Wyślij', 'language': 'Język', 'swedish': 'Szwedzki', 'english': 'Angielski', 'polish': 'Polski', 'german': 'Niemiecki',
        'msgs_in_thread': 'wiadomości w rozmowie', 'print': 'Drukuj', 'empty_trash': 'Opróżnij kosz', 'selected': 'zaznaczone',
        'create_folder': 'Utwórz nowy folder', 'folder_name': 'Nazwa folderu', 'select_icon': 'Wybierz ikonę', 'create': 'Utwórz',
        'login': 'Zaloguj się', 'remember_me': 'Zapamiętaj mnie', 'forgot_password': 'Zapomniałeś hasła?', 'welcome': 'Witamy w Zalaso Mail',
        'configure_account': 'Skonfiguruj swoje konto e-mail, aby rozpocząć', 'your_account': 'Twoje konto', 'incoming_imap': 'Przychodzące (IMAP)',
        'outgoing_smtp': 'Wychodzące (SMTP)', 'test_connection': 'Testuj połączenie', 'save_and_start': 'Zapisz i uruchom', 'testing': 'Testowanie...',
        'connection_success': '✓ Połączenie udane!', 'failed': 'Niepowodzenie', 'network_error': 'Wystąpił błąd sieci.',
        'fill_imap': 'Najpierw wypełnij wszystkie pola IMAP.', 'unsaved_changes': 'Masz niezapisane zmiany.',
        'label_created': 'Etykieta utworzona! Stosowanie do istniejących wiadomości w tle.', 'log_sent': 'Log wysłany!', 'error': 'Błąd',
        'could_not_send': 'Nie można wysłać', 'could_not_create_folder': 'Nie można utworzyć folderu', 'an_error_occurred': 'Wystąpił błąd.',
        'reply_to': 'Odpowiedź do:', 'forwarding': 'Przekazywanie', 'forwarded_message': '---------- Przekazana wiadomość ----------', 'wrote': 'napisał(a)', 'reklam': 'Reklamy',
        'remote_support': 'Zdalne wsparcie', 'generate_link': 'Generuj link', 'starting': 'Uruchamianie...', 'copy': 'Kopiuj', 'stop': 'Zatrzymaj', 'support_hint': 'Podaj ten link pomocy technicznej.',
        'ngrok_token_label': 'Ngrok Authtoken', 'ngrok_token_help': 'Wymagane. Pobierz za darmo na dashboard.ngrok.com', 'ngrok_missing': 'Brak tokenu. Wpisz go powyżej.'
    },
    'de': {
        'inbox': 'Posteingang', 'sent': 'Gesendet', 'drafts': 'Entwürfe', 'trash': 'Papierkorb', 'spam': 'Spam', 'starred': 'Markiert',
        'settings': 'Einstellungen', 'logout': 'Abmelden', 'compose': 'Verfassen', 'search_placeholder': 'In E-Mails suchen', 'no_results': 'Keine Ergebnisse gefunden',
        'folders': 'Ordner', 'my_folders': 'Meine Ordner', 'new_folder': 'Neuer Ordner',
        'delete_folder_confirm': 'Sind Sie sicher, dass Sie den Ordner "{}" löschen möchten? Alle E-Mails darin werden gelöscht.',
        'block_sender_confirm': 'Möchten Sie den Absender "{}" blockieren? Alle aktuellen und zukünftigen E-Mails von diesem Absender werden in den Spam verschoben.',
        'mark_ad_confirm': 'Möchten Sie den Absender "{}" als Werbung markieren? Alle E-Mails von diesem Absender werden in den Ordner Werbung verschoben.',
        'whitelist_sender_confirm': 'Möchten Sie "{}" als vertrauenswürdigen Absender hinzufügen? E-Mails von diesem Absender werden nicht als Spam oder Werbung gefiltert.',
        'delete_selected_confirm': 'Sind Sie sicher, dass Sie alle E-Mails auf dieser Seite löschen möchten?',
        'empty_trash_confirm': 'Sind Sie sicher, dass Sie den Papierkorb leeren möchten? Dies löscht alle E-Mails dauerhaft.',
        'undo_delete': 'Konversation gelöscht.', 'undo_move': 'Konversation verschoben.', 'undo': 'Rückgängig',
        'reply': 'Antworten', 'forward': 'Weiterleiten', 'delete': 'Löschen', 'mark_read': 'Als gelesen markieren', 'mark_unread': 'Als ungelesen markieren',
        'move_to': 'Verschieben nach', 'block_sender': 'Absender blockieren', 'mark_as_ad': 'Als Werbung markieren', 'whitelist_sender': 'Vertrauenswürdiger Absender',
        'general': 'Allgemein', 'connection': 'Verbindung', 'presets': 'Voreinstellungen', 'contacts': 'Kontakte', 'labels': 'Labels', 'rules': 'Regeln', 'filters': 'Filter', 'logs': 'Protokolle',
        'save': 'Speichern', 'cancel': 'Abbrechen', 'email_username': 'E-Mail / Benutzername', 'password': 'Passwort',
        'imap_server': 'IMAP-Server', 'port': 'Port', 'smtp_server': 'SMTP-Server', 'layout': 'Layout', 'normal': 'Normal', 'compact': 'Kompakt',
        'signature': 'Signatur', 'web_password': 'Web-Passwort (Optional)', 'web_password_placeholder': 'Leer lassen für keinen Schutz',
        'restart': 'Neustart', 'restart_confirm': 'Sind Sie sicher, dass Sie den Server neu starten möchten?',
        'app_password_hint': 'Für Gmail/Outlook: Verwenden Sie ein App-Passwort, wenn 2FA aktiviert ist.',
        'add_contact': 'Kontakt hinzufügen', 'name': 'Name', 'email': 'E-Mail', 'add': 'Hinzufügen', 'my_contacts': 'Meine Kontakte',
        'no_contacts': 'Noch keine Kontakte gespeichert.', 'create_label': 'Neues Label erstellen', 'label_name': 'Labelname', 'apply_if': 'Anwenden wenn...',
        'subject': 'Betreff', 'sender': 'Absender', 'both': 'Beide', 'keyword_placeholder': 'Stichwort (z.B. Bestellung, Rechnung)...',
        'my_labels': 'Meine Labels', 'no_labels': 'Noch keine Labels erstellt.', 'create_rule': 'Neue Regel erstellen',
        'move_to_folder': '...automatisch in Ordner verschieben:', 'select_folder': 'Ordner auswählen...', 'save_rule': 'Regel speichern',
        'active_rules': 'Aktive Regeln', 'if_sender': 'Wenn Absender:', 'if_subject_sender': 'Wenn Betreff/Absender:', 'if_subject': 'Wenn Betreff:',
        'no_rules': 'Noch keine Regeln erstellt.', 'blocked_senders': 'Blockierte Absender (Spam)', 'no_blocked': 'Keine blockierten Absender',
        'ad_senders': 'Werbeabsender', 'no_ads': 'Keine Werbeabsender', 'trusted_senders': 'Vertrauenswürdige Absender (Whitelist)',
        'no_trusted': 'Keine vertrauenswürdigen Absender', 'event_log': 'Ereignisprotokoll', 'send_to_support': 'An Support senden', 'sending': 'Senden...',
        'update': 'Aktualisieren', 'no_logs': 'Keine Protokolle verfügbar.', 'new_message': 'Neue Nachricht', 'to': 'An', 'attach_files': 'Dateien anhängen',
        'uploading': 'Hochladen...', 'send': 'Senden', 'language': 'Sprache', 'swedish': 'Schwedisch', 'english': 'Englisch', 'polish': 'Polnisch', 'german': 'Deutsch',
        'msgs_in_thread': 'Nachrichten in Konversation', 'print': 'Drucken', 'empty_trash': 'Papierkorb leeren', 'selected': 'ausgewählt',
        'create_folder': 'Neuen Ordner erstellen', 'folder_name': 'Ordnername', 'select_icon': 'Symbol auswählen', 'create': 'Erstellen',
        'login': 'Anmelden', 'remember_me': 'Angemeldet bleiben', 'forgot_password': 'Passwort vergessen?', 'welcome': 'Willkommen bei Zalaso Mail',
        'configure_account': 'Konfigurieren Sie Ihr E-Mail-Konto, um zu beginnen', 'your_account': 'Ihr Konto', 'incoming_imap': 'Eingehend (IMAP)',
        'outgoing_smtp': 'Ausgehend (SMTP)', 'test_connection': 'Verbindung testen', 'save_and_start': 'Speichern und Starten', 'testing': 'Testen...',
        'connection_success': '✓ Verbindung erfolgreich!', 'failed': 'Fehlgeschlagen', 'network_error': 'Ein Netzwerkfehler ist aufgetreten.',
        'fill_imap': 'Bitte füllen Sie zuerst alle IMAP-Felder aus.', 'unsaved_changes': 'Sie haben ungespeicherte Änderungen.',
        'label_created': 'Label erstellt! Wird im Hintergrund auf vorhandene E-Mails angewendet.', 'log_sent': 'Protokoll gesendet!', 'error': 'Fehler',
        'could_not_send': 'Konnte nicht senden', 'could_not_create_folder': 'Konnte Ordner nicht erstellen', 'an_error_occurred': 'Ein Fehler ist aufgetreten.',
        'reply_to': 'Antwort an:', 'forwarding': 'Weiterleiten', 'forwarded_message': '---------- Weitergeleitete Nachricht ----------', 'wrote': 'schrieb', 'reklam': 'Werbung',
        'remote_support': 'Fernwartung', 'generate_link': 'Link generieren', 'starting': 'Starten...', 'copy': 'Kopieren', 'stop': 'Stopp', 'support_hint': 'Geben Sie diesen Link an den Support weiter.',
        'ngrok_token_label': 'Ngrok Authtoken', 'ngrok_token_help': 'Erforderlich. Kostenlos unter dashboard.ngrok.com', 'ngrok_missing': 'Authtoken fehlt. Oben eingeben.'
    }
}

# Hjälpfunktioner för att hantera lokal läst-status
def update_local_status(folder, uids, is_read):
    data = {}
    if os.path.exists(READ_STATUS_FILE):
        try:
            with open(READ_STATUS_FILE, 'r') as f: data = json.load(f)
        except: pass
    
    if folder not in data: data[folder] = {}
    for uid in uids:
        data[folder][str(uid)] = is_read
        
    with open(READ_STATUS_FILE, 'w') as f:
        json.dump(data, f)

def update_local_status_batch(folder, updates):
    data = {}
    if os.path.exists(READ_STATUS_FILE):
        try:
            with open(READ_STATUS_FILE, 'r') as f: data = json.load(f)
        except: pass
    
    if folder not in data: data[folder] = {}
    
    changed = False
    for uid, is_read in updates.items():
        if data[folder].get(str(uid)) != is_read:
            data[folder][str(uid)] = is_read
            changed = True
            
    if changed:
        with open(READ_STATUS_FILE, 'w') as f:
            json.dump(data, f)

def get_local_status(folder):
    if not os.path.exists(READ_STATUS_FILE): return {}
    try:
        with open(READ_STATUS_FILE, 'r') as f:
            return json.load(f).get(folder, {})
    except: return {}

def update_star_status(folder, uid, is_starred):
    data = {}
    if os.path.exists(STAR_STATUS_FILE):
        try:
            with open(STAR_STATUS_FILE, 'r') as f: data = json.load(f)
        except: pass
    
    if folder not in data: data[folder] = {}
    data[folder][str(uid)] = is_starred
        
    with open(STAR_STATUS_FILE, 'w') as f:
        json.dump(data, f)

def get_star_status(folder):
    if not os.path.exists(STAR_STATUS_FILE): return {}
    try:
        with open(STAR_STATUS_FILE, 'r') as f:
            return json.load(f).get(folder, {})
    except: return {}

def update_star_status_batch(folder, updates):
    data = {}
    if os.path.exists(STAR_STATUS_FILE):
        try:
            with open(STAR_STATUS_FILE, 'r') as f: data = json.load(f)
        except: pass
    
    if folder not in data: data[folder] = {}
    
    changed = False
    for uid, is_starred in updates.items():
        if data[folder].get(uid) != is_starred:
            data[folder][uid] = is_starred
            changed = True
            
    if changed:
        with open(STAR_STATUS_FILE, 'w') as f:
            json.dump(data, f)

def get_folder_icons_map():
    if not os.path.exists(FOLDER_ICONS_FILE): return {}
    try:
        with open(FOLDER_ICONS_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_folder_icon(folder_name, icon_path):
    data = get_folder_icons_map()
    data[folder_name] = icon_path
    with open(FOLDER_ICONS_FILE, 'w') as f:
        json.dump(data, f)

def get_spam_filters():
    defaults = {
        'senders': [], 
        'subjects': ['casino', 'viagra', 'lån', 'vinst', 'bitcoin'],
        'whitelist': [],
        'ads_subjects': ['reklam', 'erbjudande', 'nyhetsbrev', 'unsubscribe', 'kampanj', 'rea', 'rabatt', 'utförsäljning'],
        'ads_senders': []
    }
    if not os.path.exists(SPAM_FILTERS_FILE):
        return defaults
    try:
        with open(SPAM_FILTERS_FILE, 'r') as f: 
            data = json.load(f)
            for k, v in defaults.items():
                if k not in data: data[k] = v
            return data
    except: return defaults

def add_spam_sender(sender):
    filters = get_spam_filters()
    if sender not in filters['senders']:
        filters['senders'].append(sender)
        if sender in filters.get('whitelist', []):
            filters['whitelist'].remove(sender)
        with open(SPAM_FILTERS_FILE, 'w') as f:
            json.dump(filters, f)

def add_ad_sender(sender):
    filters = get_spam_filters()
    if sender not in filters['ads_senders']:
        filters['ads_senders'].append(sender)
        if sender in filters.get('whitelist', []):
            filters['whitelist'].remove(sender)
        with open(SPAM_FILTERS_FILE, 'w') as f:
            json.dump(filters, f)

def add_whitelist_sender(sender):
    filters = get_spam_filters()
    if sender not in filters['whitelist']:
        filters['whitelist'].append(sender)
        if sender in filters.get('senders', []):
            filters['senders'].remove(sender)
        with open(SPAM_FILTERS_FILE, 'w') as f:
            json.dump(filters, f)

def is_spam_email(msg, filters):
    sender = (msg.from_ or "").lower()
    subject = (msg.subject or "").lower()
    
    for w in filters.get('whitelist', []):
        if w.lower() in sender: return False

    for s in filters.get('senders', []):
        if s.lower() in sender: return True
    for s in filters.get('subjects', []):
        if s.lower() in subject: return True
    return False

def is_ad_email(msg, filters):
    sender = (msg.from_ or "").lower()
    subject = (msg.subject or "").lower()
    
    for w in filters.get('whitelist', []):
        if w.lower() in sender: return False

    for s in filters.get('ads_senders', []):
        if s.lower() in sender: return True

    for s in filters.get('ads_subjects', []):
        if s.lower() in subject: return True
    return False

def load_settings():
    if not os.path.exists(SETTINGS_FILE): return {}
    try:
        with open(SETTINGS_FILE, 'r') as f:
            content = f.read().strip()
            if not content: return {}
            return json.loads(content)
    except: return {}

def is_configured():
    """ Kontrollera om nödvändiga inställningar finns """
    s = load_settings()
    return bool(s.get('email') and s.get('password') and s.get('imap_server') and s.get('smtp_server'))

def get_mailbox():
    cfg = load_settings()
    ctx = ssl.create_default_context()
    if 'zalaso' in cfg.get('imap_server',''):
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    return MailBox(cfg['imap_server'], port=int(cfg['imap_port']), ssl_context=ctx).login(cfg['email'], cfg['password'])

def parse_folder(name, t):
    n = name.lower()
    if n == 'inbox': return t['inbox'], 'inbox.png', True, True
    if 'sent' in n or 'skickat' in n: return t['sent'], 'sent.png', True, True
    if 'draft' in n or 'utkast' in n: return t['drafts'], 'draft.png', True, True
    if 'trash' in n or 'bin' in n or 'papperskorg' in n: return t['trash'], 'trash.png', True, True
    if 'spam' in n or 'junk' in n: return t['spam'], 'spam.png', True, True
    if 'reklam' in n: return t['reklam'], 'reklam.png', True, True
    return name.replace('INBOX.', '').replace('.', ' '), '📁', False, False

DB_FILE = get_data_path('zalaso.db')

def init_db():
    with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('''CREATE TABLE IF NOT EXISTS emails (
            uid INTEGER, folder TEXT, subject TEXT, sender TEXT, 
            body TEXT, html TEXT, date_iso TEXT, date_str TEXT, attachments TEXT,
            PRIMARY KEY(uid, folder)
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS local_folders (name TEXT PRIMARY KEY)''')
        conn.execute('''CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT UNIQUE
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT,
            target_folder TEXT
        )''')
        conn.execute('''CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            color TEXT,
            keyword TEXT,
            check_field TEXT DEFAULT "subject"
        )''')
        try:
            conn.execute('ALTER TABLE emails ADD COLUMN recipients TEXT')
        except: pass
        try:
            conn.execute('ALTER TABLE rules ADD COLUMN check_field TEXT DEFAULT "subject"')
        except: pass
        try:
            conn.execute('ALTER TABLE emails ADD COLUMN labels TEXT')
        except: pass
        conn.execute('''CREATE VIRTUAL TABLE IF NOT EXISTS emails_fts USING fts5(subject, sender, body, content='emails', content_rowid='rowid')''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS emails_ai AFTER INSERT ON emails BEGIN
            INSERT INTO emails_fts(rowid, subject, sender, body) VALUES (new.rowid, new.subject, new.sender, new.body);
        END;''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS emails_ad AFTER DELETE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, sender, body) VALUES('delete', old.rowid, old.subject, old.sender, old.body);
        END;''')
        conn.execute('''CREATE TRIGGER IF NOT EXISTS emails_au AFTER UPDATE ON emails BEGIN
            INSERT INTO emails_fts(emails_fts, rowid, subject, sender, body) VALUES('delete', old.rowid, old.subject, old.sender, old.body);
            INSERT INTO emails_fts(rowid, subject, sender, body) VALUES (new.rowid, new.subject, new.sender, new.body);
        END;''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_emails_folder_date ON emails(folder, date_iso DESC)''')
        conn.execute('''CREATE INDEX IF NOT EXISTS idx_emails_labels ON emails(labels)''')

sync_lock = threading.Lock()
syncing_folders = set()

def sync_folder_structure():
    """ Hämta mappstruktur från servern och spara lokalt (för snabbare laddning) """
    try:
        with get_mailbox() as mb:
            # Loopia-fix: Subscribe
            try:
                for f in mb.folder.list():
                    try: mb.folder.subscribe(f.name)
                    except: pass
            except: pass

            folders = list(mb.folder.list())
            # Ensure Reklam exists
            if not any('reklam' in f.name.lower() for f in folders):
                try:
                    mb.folder.create('INBOX.Reklam')
                    folders = list(mb.folder.list())
                except: pass
            
            folder_names = [f.name for f in folders]
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                conn.execute("DELETE FROM local_folders")
                conn.executemany("INSERT INTO local_folders (name) VALUES (?)", [(n,) for n in folder_names])
    except Exception as e: log_event(f"Folder sync error: {e}")

def subscribe_worker(folder_names=None):
    """ Bakgrundsjobb för att säkerställa att alla mappar är prenumererade (Loopia-fix) """
    try:
        with get_mailbox() as mb:
            if folder_names is None:
                folder_names = [f.name for f in mb.folder.list()]
            
            for name in folder_names:
                try: mb.folder.subscribe(name)
                except: pass
    except Exception as e: log_event(f"Subscribe worker error: {e}")

def sync_worker(folder):
    with sync_lock:
        if folder in syncing_folders: return
        syncing_folders.add(folder)
    try:
        log_event(f"Synkroniserar mapp: {folder}")
        with get_mailbox() as mb:
            mb.folder.set(folder)
            try: mb.check()
            except: pass
            
            # Hitta spam-mapp för filtrering
            spam_folder = None
            ad_folder = None
            if folder.lower() == 'inbox':
                for f in mb.folder.list():
                    if 'spam' in f.name.lower() or 'junk' in f.name.lower() or 'skräppost' in f.name.lower():
                        spam_folder = f.name
                    if 'reklam' in f.name.lower():
                        ad_folder = f.name

            server_uids = {int(u) for u in mb.uids()}
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                # Hämta lokala UIDs och kolla om de har innehåll (html)
                rows = conn.execute("SELECT uid, length(html) FROM emails WHERE folder=?", (folder,)).fetchall()
                local_uids = {r[0] for r in rows if r[0] is not None}
                incomplete_uids = {r[0] for r in rows if (not r[1] or r[1] == 0) and r[0] is not None} # UIDs som saknar kropp
                
                # Städa bort rader med NULL UID eller 0 som kan ha fastnat
                if any(r[0] is None or r[0] == 0 for r in rows):
                    conn.execute("DELETE FROM emails WHERE (uid IS NULL OR uid=0) AND folder=?", (folder,))
            
            to_delete = list(local_uids - server_uids)
            if to_delete:
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    conn.executemany("DELETE FROM emails WHERE uid=? AND folder=?", [(u, folder) for u in to_delete])

            # FAS 1: Hämta rubriker för ALLA nya mail (Blixtsnabbt)
            to_fetch_headers = list(server_uids - local_uids)
            to_fetch_headers.sort(reverse=True)
            
            # Hämta regler
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                db_rules = conn.execute("SELECT keyword, target_folder, check_field FROM rules").fetchall()
                db_labels = conn.execute("SELECT id, keyword, check_field FROM labels").fetchall()
            
            filters = get_spam_filters()
            
            if to_fetch_headers:
                for i in range(0, len(to_fetch_headers), 50):
                    chunk = [str(u) for u in to_fetch_headers[i:i+50]]
                    new_rows = []
                    spam_uids = []
                    ad_uids = []
                    try:
                        for msg in mb.fetch(A(uid=chunk), headers_only=True, bulk=True):
                            if not msg.uid or msg.uid == 0: continue
                            
                            subj_lower = (msg.subject or "").lower()
                            sender_lower = (msg.from_ or "").lower()

                            # Etiketter
                            applied_labels = []
                            for l_id, l_key, l_field in db_labels:
                                l_field = (l_field or 'subject').lower()
                                keywords = [k.strip().lower() for k in (l_key or "").split(',') if k.strip()]
                                is_match = False
                                
                                for k in keywords:
                                    if l_field == 'sender':
                                        if k in sender_lower: is_match = True
                                    elif l_field == 'both':
                                        if k in subj_lower or k in sender_lower: is_match = True
                                    else: # subject
                                        if k in subj_lower: is_match = True
                                    if is_match: break
                                
                                if is_match: applied_labels.append(l_id)

                            # Spam-check för INBOX
                            if folder.lower() == 'inbox':
                                # 1. Kolla regler (Regler går före spam)
                                rule_target = None
                                subj_lower = (msg.subject or "").lower()
                                sender_lower = (msg.from_ or "").lower()
                                
                                for r_key, r_folder, r_field in db_rules:
                                    r_field = (r_field or 'subject').lower()
                                    is_match = False
                                    if r_field == 'sender':
                                        if r_key.lower() in sender_lower: is_match = True
                                    elif r_field == 'both':
                                        if r_key.lower() in subj_lower or r_key.lower() in sender_lower: is_match = True
                                    else: # subject
                                        if r_key.lower() in subj_lower: is_match = True
                                    
                                    if is_match:
                                        rule_target = r_folder
                                        break
                                if rule_target:
                                    try:
                                        mb.move([msg.uid], rule_target)
                                        threading.Thread(target=sync_worker, args=(rule_target,), daemon=True).start()
                                        continue # Hoppa över att spara i INBOX lokalt
                                    except: pass

                                if is_spam_email(msg, filters):
                                    if spam_folder:
                                        spam_uids.append(msg.uid)
                                        continue
                                elif is_ad_email(msg, filters):
                                    ad_uids.append(msg.uid)
                                    continue

                            d_iso = msg.date.isoformat() if msg.date else datetime.now().isoformat()
                            d_str = msg.date.strftime('%Y-%m-%d %H:%M') if msg.date else datetime.now().strftime('%Y-%m-%d %H:%M')
                            # Spara med tomt innehåll först så de blir sökbara direkt
                            sender_name = msg.from_ or ""
                            try:
                                if msg.from_values and msg.from_values.name:
                                    sender_name = f"{msg.from_values.name} <{msg.from_}>"
                            except: pass
                            
                            recipients = []
                            try:
                                if msg.to_values:
                                    for r in msg.to_values:
                                        recipients.append(r.name or r.email or "")
                            except: pass
                            recipients_str = ", ".join(recipients)

                            new_rows.append((msg.uid, folder, msg.subject or "", sender_name, "", "", d_iso, d_str, "[]", recipients_str, json.dumps(applied_labels)))
                    except Exception as e:
                        log_event(f"Fel vid hämtning av mail (chunk {i}): {e}")
                    
                    if new_rows:
                        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                            conn.executemany("INSERT OR REPLACE INTO emails (uid, folder, subject, sender, body, html, date_iso, date_str, attachments, recipients, labels) VALUES (?,?,?,?,?,?,?,?,?,?,?)", new_rows)
                    
                    # Flytta spam
                    if spam_uids and spam_folder:
                        try: mb.move(spam_uids, spam_folder)
                        except:
                            try:
                                mb.copy(spam_uids, spam_folder)
                                mb.delete(spam_uids)
                            except: pass
                    
                    # Flytta reklam
                    if ad_uids:
                        target_ad_folder = ad_folder or 'INBOX.Reklam'
                        try:
                            mb.move(ad_uids, target_ad_folder)
                        except:
                            try:
                                try: mb.folder.create(target_ad_folder)
                                except: pass
                                
                                try:
                                    mb.move(ad_uids, target_ad_folder)
                                except:
                                    mb.copy(ad_uids, target_ad_folder)
                                    mb.delete(ad_uids)
                            except: pass

            # FAS 2: Hämta innehåll för mail som saknar det (Bakgrund)
            to_fetch_bodies = list(incomplete_uids.union(set(to_fetch_headers)))
            to_fetch_bodies.sort(reverse=True)
            
            if to_fetch_bodies:
                for i in range(0, len(to_fetch_bodies), 100):
                    chunk = [str(u) for u in to_fetch_bodies[i:i+100]]
                    update_rows = []
                    try:
                        for msg in mb.fetch(A(uid=chunk), bulk=True):
                            body_html = msg.html or f"<pre>{msg.text}</pre>"
                            for att in msg.attachments:
                                if att.content_id:
                                    try:
                                        b64 = base64.b64encode(att.payload).decode('utf-8')
                                        body_html = body_html.replace(f"cid:{att.content_id.strip('<>')}", f"data:{att.content_type};base64,{b64}")
                                    except: pass
                            
                            atts = []
                            for a in msg.attachments:
                                # Filtrera bort inline-bilder (som har Content-ID eller disposition inline)
                                is_inline = False
                                if a.content_id: is_inline = True
                                if a.content_disposition and a.content_disposition.lower() == 'inline': is_inline = True
                                
                                # Filtrera bort alla bilder (användaren vill bara se dokument)
                                is_image = a.content_type and a.content_type.lower().startswith('image/')
                                
                                if not is_inline and not is_image:
                                    atts.append({'filename': a.filename or "noname", 'size': a.size, 'content_type': a.content_type})
                            
                            update_rows.append((msg.text or "", body_html, json.dumps(atts), msg.uid, folder))
                    except: pass
                    
                    if update_rows:
                        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                            conn.executemany("UPDATE emails SET body=?, html=?, attachments=? WHERE uid=? AND folder=?", update_rows)
            
            # FAS 3: Synka flaggor (Läst/Stjärnmärkt) för synliga mail i bakgrunden
            try:
                recent_uids = sorted(list(local_uids), reverse=True)[:100]
                if recent_uids:
                    uid_str = [str(u) for u in recent_uids]
                    flags_map = {}
                    # Hämta bara flaggor (snabbt)
                    for msg in mb.fetch(A(uid=uid_str), ['FLAGS', 'UID']):
                        flags_map[str(msg.uid)] = msg.flags
                    
                    read_updates = {}
                    star_updates = {}
                    for uid in uid_str:
                        flags = flags_map.get(uid, [])
                        is_read = '\\Seen' in flags
                        is_starred = '\\Flagged' in flags
                        read_updates[uid] = is_read
                        star_updates[uid] = is_starred
                    
                    update_local_status_batch(folder, read_updates)
                    update_star_status_batch(folder, star_updates)
            except Exception as e: log_event(f"Flag sync error: {e}")
    except Exception as e:
        log_event(f"Synkroniseringsfel för {folder}: {e}")
    finally:
        with sync_lock: syncing_folders.remove(folder)

class MockMsg:
    def __init__(self, row):
        self.uid = 0
        self.from_ = "Okänd"
        self.subject = "Inget ämne"
        self.text = ""
        self.html = ""
        self.date_str = ""
        self.original_folder = "INBOX"
        self.recipients = ""
        self.date = datetime(1970, 1, 1)
        self.attachments_data = []
        self.flags = []
        self.attachments = []
        self.labels = []

        try:
            if row:
                self.uid = row['uid'] if row['uid'] is not None else 0
                self.from_ = row['sender'] or "Okänd"
                self.subject = row['subject'] or "Inget ämne"
                self.text = row['body'] or ""
                self.html = row['html'] or ""
                self.date_str = row['date_str'] or ""
                self.original_folder = row['folder'] or 'INBOX'
                try: self.recipients = row['recipients'] or ""
                except: pass
                
                if row['date_iso']:
                    try: self.date = datetime.fromisoformat(row['date_iso'])
                    except: pass
                    
                if row['attachments']:
                    try:
                        data = json.loads(row['attachments'])
                        if isinstance(data, list): self.attachments_data = data
                    except: pass
                
                if 'labels' in row.keys() and row['labels']:
                    try: self.labels = json.loads(row['labels'])
                    except: pass
        except: pass

def move_existing_spam(sender):
    # Flytta befintliga mail från denna avsändare till spam
    try:
        with get_mailbox() as mb:
            # Hitta spam-mapp
            spam_folder = None
            folders = mb.folder.list()
            for f in folders:
                if 'spam' in f.name.lower() or 'junk' in f.name.lower() or 'skräppost' in f.name.lower():
                    spam_folder = f.name
                    break
            
            if not spam_folder: return

            # Sök i INBOX
            mb.folder.set('INBOX')
            
            # Hitta UIDs som matchar avsändaren
            uids_to_move = []
            # Vi söker i DB först för att få UIDs snabbt
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                rows = conn.execute("SELECT uid FROM emails WHERE folder='INBOX' AND sender LIKE ?", (f'%{sender}%',)).fetchall()
                uids_to_move = [str(r[0]) for r in rows]
            
            if uids_to_move:
                try:
                    mb.move(uids_to_move, spam_folder)
                except:
                    mb.copy(uids_to_move, spam_folder)
                    mb.delete(uids_to_move)
                
                # Ta bort från lokal DB (INBOX)
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    placeholders = ','.join('?' * len(uids_to_move))
                    conn.execute(f"DELETE FROM emails WHERE folder='INBOX' AND uid IN ({placeholders})", uids_to_move)
    except Exception as e: log_event(f"Error moving existing spam: {e}")

def move_existing_ads(sender):
    # Flytta befintliga mail från denna avsändare till reklam
    try:
        with get_mailbox() as mb:
            # Hitta reklam-mapp
            ad_folder = None
            folders = mb.folder.list()
            for f in folders:
                if 'reklam' in f.name.lower():
                    ad_folder = f.name
                    break
            
            if not ad_folder: 
                ad_folder = 'INBOX.Reklam'
                try: mb.folder.create(ad_folder)
                except: pass

            # Sök i INBOX
            mb.folder.set('INBOX')
            
            # Hitta UIDs som matchar avsändaren
            uids_to_move = []
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                rows = conn.execute("SELECT uid FROM emails WHERE folder='INBOX' AND sender LIKE ?", (f'%{sender}%',)).fetchall()
                uids_to_move = [str(r[0]) for r in rows]
            
            if uids_to_move:
                try:
                    mb.move(uids_to_move, ad_folder)
                except:
                    mb.copy(uids_to_move, ad_folder)
                    mb.delete(uids_to_move)
                
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    placeholders = ','.join('?' * len(uids_to_move))
                    conn.execute(f"DELETE FROM emails WHERE folder='INBOX' AND uid IN ({placeholders})", uids_to_move)
    except Exception as e: log_event(f"Error moving existing ads: {e}")

def apply_labels_to_all():
    """ Applicera etiketter på alla befintliga mail """
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            db_labels = conn.execute("SELECT id, keyword, check_field FROM labels").fetchall()
            emails = conn.execute("SELECT uid, folder, subject, sender FROM emails").fetchall()
            
            updates = []
            for uid, folder, subj, sender in emails:
                subj_lower = (subj or "").lower()
                sender_lower = (sender or "").lower()
                applied = []
                for l_id, l_key, l_field in db_labels:
                    l_field = (l_field or 'subject').lower()
                    keywords = [k.strip().lower() for k in (l_key or "").split(',') if k.strip()]
                    is_match = False
                    
                    for k in keywords:
                        if l_field == 'sender':
                            if k in sender_lower: is_match = True
                        elif l_field == 'both':
                            if k in subj_lower or k in sender_lower: is_match = True
                        else:
                            if k in subj_lower: is_match = True
                        if is_match: break
                        
                    if is_match: applied.append(l_id)
                updates.append((json.dumps(applied), uid, folder))
            conn.executemany("UPDATE emails SET labels=? WHERE uid=? AND folder=?", updates)
    except Exception as e: log_event(f"Error applying labels: {e}")

def get_language():
    s = load_settings()
    return s.get('language', 'sv')

def get_translations(lang=None):
    if not lang: lang = get_language()
    return TRANSLATIONS.get(lang, TRANSLATIONS['sv'])

@app.after_request
def add_header(response):
    if request.endpoint == 'index':
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
    return response

@app.before_request
def require_login():
    # Säkerställ att databasen finns och har tabeller (om den raderats manuellt)
    if request.endpoint != 'static':
        if not os.path.exists(DB_FILE):
            init_db()
        else:
            try:
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    conn.execute("SELECT 1 FROM emails LIMIT 1")
            except: init_db()

    if request.endpoint in ['static', 'setup', 'save_settings', 'test_connection']:
        return
    
    if not is_configured():
        return redirect(url_for('setup'))

    if request.endpoint == 'login':
        return

    settings = load_settings()
    web_password = settings.get('web_password')
    
    if web_password and not session.get('logged_in'):
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    settings = load_settings()
    lang = get_language()
    t = get_translations(lang)
    # Om inget webb-lösenord är satt, skicka direkt till inkorgen
    if not settings.get('web_password'):
        return redirect(url_for('index'))

    if request.method == 'POST':
        password = request.form.get('password')
        settings = load_settings()
        if password == settings.get('web_password'):
            session['logged_in'] = True
            if request.form.get('remember'):
                session.permanent = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="Fel lösenord", t=t)
    return render_template('login.html', t=t)

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    settings = load_settings()
    if not settings.get('web_password'):
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/setup')
def setup():
    if is_configured():
        return redirect(url_for('index'))
    lang = get_language()
    t = get_translations(lang)
    if not t: t = TRANSLATIONS['sv']
    return render_template('setup.html', t=t)

@app.route('/')
def index():
    folder = request.args.get('folder', 'INBOX')
    query = request.args.get('q', '').strip()
    page = int(request.args.get('page', 1))
    per_page = 50
    settings = load_settings()
    lang = get_language()
    t = get_translations(lang)
    
    is_trash = 'trash' in folder.lower() or 'papperskorg' in folder.lower() or 'bin' in folder.lower() or 'deleted' in folder.lower()
    folders_data = []
    
    # Lägg till Stjärnmärkt manuellt
    folders_data.append({'id': 'STARRED', 'name': t['starred'], 'icon': 'star.png', 'is_system': True, 'is_image': True})

    if folder != 'STARRED':
        threading.Thread(target=sync_worker, args=(folder,), daemon=True).start()

    # Starta mapp-synk i bakgrunden
    threading.Thread(target=sync_folder_structure, daemon=True).start()

    # Hämta etikett-definitioner och lista för sidebar
    labels_map = {}
    labels_list = []
    with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
        conn.row_factory = sqlite3.Row
        for r in conn.execute("SELECT * FROM labels ORDER BY name").fetchall():
            labels_list.append(dict(r))
            labels_map[r['id']] = {'name': r['name'], 'color': r['color']}

    try:
        # Hämta mappar från lokal DB istället för IMAP (Mycket snabbare)
        icons_map = get_folder_icons_map()
        all_folders = []
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            try:
                rows = conn.execute("SELECT name FROM local_folders").fetchall()
                for r in rows:
                    class MockFolder: pass
                    f = MockFolder()
                    f.name = r[0]
                    all_folders.append(f)
            except: pass
        
        # Fallback: Om inga mappar finns (första körning), hämta synkront
        if not all_folders:
            sync_folder_structure()
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                rows = conn.execute("SELECT name FROM local_folders").fetchall()
                for r in rows:
                    class MockFolder: pass
                    f = MockFolder()
                    f.name = r[0]
                    all_folders.append(f)

        for f in all_folders:
            dname, icon, is_sys, is_img = parse_folder(f.name, t)
            if f.name in icons_map:
                icon = 'folder/' + icons_map[f.name]
                is_img = True
            folders_data.append({'id': f.name, 'name': dname, 'icon': icon, 'is_system': is_sys, 'is_image': is_img})
        folders_data.sort(key=lambda x: (
            0 if x['id'] == 'STARRED' else 
            1 if x['id'].lower() == 'inbox' else 
            2 if x['is_system'] else 3, 
            x['name']))
        
        trash_folder_id = None
        for f in folders_data:
            if 'trash' in f['id'].lower() or 'papperskorg' in f['id'].lower() or 'bin' in f['id'].lower() or 'deleted' in f['id'].lower():
                trash_folder_id = f['id']
                break
        
        local_status = get_local_status(folder)
        star_status = get_star_status(folder)
        
        if folder == 'STARRED':
            # Hämta alla stjärnmärkta mail från alla mappar
            starred_entries = set()
            if os.path.exists(STAR_STATUS_FILE):
                try:
                    with open(STAR_STATUS_FILE) as f:
                        all_stars = json.load(f)
                        for fldr, uids in all_stars.items():
                            for uid, is_starred in uids.items():
                                if is_starred:
                                    try: starred_entries.add((fldr, int(uid)))
                                    except: pass
                except: pass
            
            mails = []
            if starred_entries:
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    conn.row_factory = sqlite3.Row
                    for fldr, uid in starred_entries:
                        try:
                            row = conn.execute("SELECT * FROM emails WHERE folder=? AND uid=?", (fldr, uid)).fetchone()
                            if row:
                                mails.append(MockMsg(row))
                        except: pass
            
            mails.sort(key=lambda x: x.date, reverse=True)
            
            total = len(mails)
            mails = mails[(page-1)*per_page : page*per_page]

        elif query:
            # Sök i lokal databas (Blixtsnabbt)
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                conn.row_factory = sqlite3.Row
                clean_query = query.replace('"', '').strip()
                
                if clean_query.startswith('*.'):
                    # Sökning på bilagor (t.ex. *.pdf)
                    ext = clean_query[1:]
                    rows = conn.execute("SELECT * FROM emails WHERE attachments LIKE ? ORDER BY date_iso DESC, uid DESC", (f'%{ext}"%',)).fetchall()
                else:
                    # FTS sökning
                    fts_query = f'{clean_query}*'
                    rows = conn.execute("SELECT * FROM emails WHERE rowid IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ? ORDER BY rank) ORDER BY date_iso DESC, uid DESC", (fts_query,)).fetchall()
                
                mails = []
                for row in rows:
                    # Simulera objektstruktur för loopen nedan
                    m = MockMsg(row)
                    mails.append(m)
                
                total = len(mails)
                # Paginering för sökresultat
                mails = mails[(page-1)*per_page : page*per_page]

        elif folder.startswith('LABEL:'):
            try:
                label_id = int(folder.split(':')[1])
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    conn.row_factory = sqlite3.Row
                    # Hämta alla mail som har etiketter och filtrera i Python
                    # Optimering: Använd LIKE för att grovsortera i SQL (mycket snabbare än att hämta allt)
                    # Vi söker på label_id som del av strängen. Python-loopen nedan verifierar exakt matchning.
                    like_pattern = f'%{label_id}%'
                    all_labeled = conn.execute("SELECT uid, labels, date_iso FROM emails WHERE labels LIKE ? ORDER BY date_iso DESC", (like_pattern,)).fetchall()
                    
                    filtered_uids = []
                    for r in all_labeled:
                        try:
                            if label_id in json.loads(r['labels']):
                                filtered_uids.append(r['uid'])
                        except: pass
                    
                    total = len(filtered_uids)
                    page_uids = filtered_uids[(page-1)*per_page : page*per_page]
                    
                    if page_uids:
                        placeholders = ','.join('?' * len(page_uids))
                        rows = conn.execute(f"SELECT * FROM emails WHERE uid IN ({placeholders})", page_uids).fetchall()
                        rows.sort(key=lambda x: x['date_iso'] or '', reverse=True)
                        mails = [MockMsg(row) for row in rows]
                    else: mails = []
            except: mails = []

        else:
            # DB fetch for speed (Fix Issue 1 & 3)
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                conn.row_factory = sqlite3.Row
                total = conn.execute("SELECT COUNT(*) FROM emails WHERE folder=? AND uid IS NOT NULL AND uid != 0", (folder,)).fetchone()[0]
                rows = conn.execute("SELECT * FROM emails WHERE folder=? AND uid IS NOT NULL AND uid != 0 ORDER BY date_iso DESC, uid DESC LIMIT ? OFFSET ?", (folder, per_page, (page-1)*per_page)).fetchall()
                mails = [MockMsg(row) for row in rows]

        months_sv = ["jan", "feb", "mar", "apr", "maj", "jun", "jul", "aug", "sep", "okt", "nov", "dec"]
        # Svensk tidszon (UTC+1) för att fixa 1 timmes felvisning
        swe_tz = timezone(timedelta(hours=1))
        now = datetime.now(swe_tz)

        threads = {}
        for msg in mails:
            sender = msg.from_ or "Okänd"
            
            if 'sent' in folder.lower() or 'skickat' in folder.lower():
                if hasattr(msg, 'recipients') and msg.recipients:
                    sender = f"Till: {msg.recipients}"
                full_sender = sender
            else:
                full_sender = sender
                email_address = ""
                
                # Extrahera namn och e-post
                if '<' in sender and '>' in sender:
                    try:
                        parts = sender.split('<')
                        name_part = parts[0].strip().replace('"', '')
                        email_address = parts[1].strip('>').strip()
                        sender = name_part if name_part else email_address
                    except: 
                        email_address = sender
                else:
                    email_address = sender

                # Förbättra namnet om det är generiskt (t.ex. "Info" -> "Företagsnamn")
                if '@' in email_address:
                    try:
                        local_part, domain = email_address.split('@')
                        generic_names = ['info', 'kontakt', 'contact', 'support', 'admin', 'noreply', 'no-reply', 'hello', 'hej', 'order', 'sales', 'salj', 'faktura', 'invoice', 'team', 'nyhetsbrev', 'kundservice', 'kundtjanst']
                        
                        current_name_lower = sender.lower().strip()
                        is_generic = (current_name_lower in generic_names) or \
                                     (current_name_lower == local_part.lower() and local_part.lower() in generic_names) or \
                                     (current_name_lower == email_address.lower() and local_part.lower() in generic_names)

                        if is_generic:
                            # Använd domänen som namn (t.ex. loopia.se -> Loopia)
                            domain_parts = domain.split('.')
                            if len(domain_parts) >= 2:
                                company_name = domain_parts[0].title()
                                # Undvik subdomäner som 'mail', 'smtp'
                                if company_name.lower() in ['mail', 'smtp', 'webmail'] and len(domain_parts) > 2:
                                    company_name = domain_parts[1].title()
                                sender = company_name
                        elif sender == email_address:
                            # Snygga till local part om inget namn fanns
                            sender = local_part.replace('.', ' ').replace('_', ' ').title()
                    except: pass

            clean_subj = (msg.subject or "Inget ämne").replace('Re: ','').replace('Sv: ','').strip()
            
            # Logik för trådning:
            # Separera utkast och mail utan ämne för att undvika problem med radering
            is_draft = 'draft' in folder.lower() or 'utkast' in folder.lower()
            has_no_subject = not msg.subject or not msg.subject.strip()
            
            if is_draft or has_no_subject:
                unique_key = f"{msg.uid}_{getattr(msg, 'original_folder', folder)}"
                tid = hashlib.md5(unique_key.encode()).hexdigest()
            else:
                thread_key = f"{clean_subj}-{sender}"
                tid = hashlib.md5(thread_key.encode()).hexdigest()

            if tid not in threads: threads[tid] = {'subject': clean_subj, 'msgs': [], 'unread': False, 'starred': False, 'thread_attachments': [], 'labels': set()}

            # Hantera MockMsg (från DB) vs IMAP Message
            if hasattr(msg, 'attachments_data'):
                body_html = msg.html
                if not body_html and msg.text:
                    body_html = f"<pre>{msg.text}</pre>"
                atts = msg.attachments_data
            else:
                # Fallback för direkta IMAP-objekt (om det skulle användas)
                body_html = msg.html or f"<pre>{msg.text}</pre>"
                for att in msg.attachments:
                    if att.content_id:
                        try:
                            b64_data = base64.b64encode(att.payload).decode('utf-8')
                            body_html = body_html.replace(f"cid:{att.content_id.strip('<>')}", f"data:{att.content_type};base64,{b64_data}")
                        except: pass
                atts = [{'filename': a.filename or "noname", 'size': a.size, 'content_type': a.content_type} for a in msg.attachments]

            # Filtrera bort bilder från visning (för befintliga mail i DB)
            atts = [a for a in atts if not (a.get('content_type') or '').lower().startswith('image/')]

            # Använd body_html för safe_body för att behålla formatering i Svara/Vidarebefordra
            # Vi rensar script för säkerhet i editorn
            safe_html = body_html
            if safe_html:
                safe_html = re.sub(r'<script[^>]*>.*?</script>', '', safe_html, flags=re.DOTALL|re.IGNORECASE)
            else:
                # Fallback till text med radbrytningar om ingen HTML finns
                safe_html = (msg.text or "").replace('\n', '<br>')

            safe_body = base64.b64encode((safe_html or "").encode('utf-8', 'ignore')).decode('utf-8')

            # Datumformatering likt Gmail
            date_str = ""
            if msg.date and msg.date.year > 1970:
                # Säkerställ tidszon och konvertera till svensk tid
                d = msg.date
                if d.tzinfo is None:
                    d = d.replace(tzinfo=timezone.utc)
                local_date = d.astimezone(swe_tz)

                if local_date.date() == now.date():
                    date_str = local_date.strftime('%H:%M')
                elif local_date.year == now.year:
                    date_str = f"{months_sv[local_date.month-1]} {local_date.day}"
                else:
                    date_str = local_date.strftime('%Y-%m-%d')

            # Kolla lokal status. Om den inte finns, anta att mailet är oläst (första gången).
            # För STARRED måste vi kolla status i originalmappen
            check_folder = getattr(msg, 'original_folder', folder)
            check_status = get_local_status(check_folder)
            
            if str(msg.uid) in check_status:
                is_read = check_status[str(msg.uid)]
            else:
                is_read = False

            if not is_read: threads[tid]['unread'] = True

            # Hantera stjärnstatus
            is_starred = False
            if hasattr(msg, 'flags') and '\\Flagged' in msg.flags: is_starred = True
            
            # För STARRED är allt per definition stjärnmärkt, annars kolla status
            if folder == 'STARRED':
                is_starred = True
            elif str(msg.uid) in star_status: 
                is_starred = star_status[str(msg.uid)]
            
            if is_starred: threads[tid]['starred'] = True

            threads[tid]['msgs'].append({
                'uid': str(msg.uid),
                'folder': getattr(msg, 'original_folder', folder),
                'from': sender,
                'from_full': full_sender,
                'date': date_str,
                'body_html': body_html,
                'body_safe': safe_body,
                'has_body': bool(body_html or safe_body),
                'attachments': atts
            })

            for l in msg.labels:
                threads[tid]['labels'].add(l)

            # Samla unika bilagor för tråden (för inkorgs-vyn)
            # Prioritera bilagor med storlek > 0 om dubbletter finns (t.ex. vid svar)
            for att in atts:
                existing_idx = next((i for i, a in enumerate(threads[tid]['thread_attachments']) if a['filename'] == att['filename']), -1)
                if existing_idx == -1:
                    a_copy = att.copy()
                    a_copy['uid'] = str(msg.uid)
                    a_copy['folder'] = getattr(msg, 'original_folder', folder)
                    threads[tid]['thread_attachments'].append(a_copy)
                else:
                    if threads[tid]['thread_attachments'][existing_idx].get('size', 0) == 0 and att.get('size', 0) > 0:
                        a_copy = att.copy()
                        a_copy['uid'] = str(msg.uid)
                        a_copy['folder'] = getattr(msg, 'original_folder', folder)
                        threads[tid]['thread_attachments'][existing_idx] = a_copy
        
        total_pages = max(1, (total + per_page - 1) // per_page)
        
        start_idx = (page - 1) * per_page + 1 if total > 0 else 0
        end_idx = min(page * per_page, total)
        
        base_url = url_for("index", folder=folder, q=query)
        
        pagination_html = '<div class="flex items-center justify-end gap-2 text-sm text-gray-600 my-2">'
        pagination_html += f'<span class="mr-2">{start_idx}-{end_idx} av {total}</span>'
        
        if page > 1:
            prev_url = url_for("index", folder=folder, page=page-1, q=query)
            pagination_html += f'<a href="{prev_url}" class="p-1.5 hover:bg-gray-100 rounded-full text-gray-600 transition" title="Föregående"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" /></svg></a>'
        else:
            pagination_html += '<span class="p-1.5 text-gray-300 cursor-not-allowed"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M12.707 5.293a1 1 0 010 1.414L9.414 10l3.293 3.293a1 1 0 01-1.414 1.414l-4-4a1 1 0 010-1.414l4-4a1 1 0 011.414 0z" clip-rule="evenodd" /></svg></span>'
        
        # Input för sidnummer
        pagination_html += f'''
        <div class="flex items-center gap-1 mx-1">
            <input type="number" value="{page}" min="1" max="{total_pages}" 
                   class="w-12 p-1 text-center border border-gray-300 rounded text-xs focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none"
                   onkeydown="if(event.key==='Enter'){{ window.location.href='{base_url}&page='+this.value; }}">
            <span class="text-gray-400 text-xs">/ {total_pages}</span>
        </div>
        '''
            
        if page < total_pages:
            next_url = url_for("index", folder=folder, page=page+1, q=query)
            pagination_html += f'<a href="{next_url}" class="p-1.5 hover:bg-gray-100 rounded-full text-gray-600 transition" title="Nästa"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" /></svg></a>'
        else:
            pagination_html += '<span class="p-1.5 text-gray-300 cursor-not-allowed"><svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fill-rule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" clip-rule="evenodd" /></svg></span>'
        
        pagination_html += '</div>'
        
        return render_template('index.html', threads=threads, folders=folders_data, current_folder=folder, current_page=page, total_pages=total_pages, pagination_html=pagination_html, settings=settings, query=query, is_trash=is_trash, trash_folder_id=trash_folder_id, labels_map=labels_map, labels_list=labels_list, t=t, lang=lang)
    except Exception as e:
        return render_template('index.html', threads={}, folders=folders_data, current_folder=folder, error=str(e), settings=settings, query=query, trash_folder_id=None, labels_map={}, labels_list=labels_list, t=t, lang=lang)

@app.route('/api/get_message/<uid>')
def get_message_api(uid):
    folder = request.args.get('folder', 'INBOX')
    
    def process_msg_data(html_content, text_content, attachments_json=None, attachments_list=None):
        if not html_content and text_content:
            html_content = f"<pre>{text_content}</pre>"
        
        atts = []
        if attachments_json:
            try: 
                atts = json.loads(attachments_json)
                atts = [a for a in atts if not (a.get('content_type') or '').lower().startswith('image/')]
            except: pass
        elif attachments_list:
            atts = [{'filename': a.filename or "noname", 'size': a.size, 'content_type': a.content_type} for a in attachments_list]
            atts = [a for a in atts if not (a.get('content_type') or '').lower().startswith('image/')]

        safe_html = html_content
        if safe_html:
            safe_html = re.sub(r'<script[^>]*>.*?</script>', '', safe_html, flags=re.DOTALL|re.IGNORECASE)
        else:
            safe_html = (text_content or "").replace('\n', '<br>')

        safe_body = base64.b64encode((safe_html or "").encode('utf-8', 'ignore')).decode('utf-8')
        
        return {
            'uid': str(uid),
            'body_safe': safe_body,
            'attachments': atts
        }

    try:
        # 1. Försök hämta från DB först
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM emails WHERE uid=? AND folder=?", (uid, folder)).fetchone()
            if row and (row['html'] or row['body']):
                data = process_msg_data(row['html'], row['body'], attachments_json=row['attachments'])
                data['subject'] = row['subject']
                data['from'] = row['sender']
                return json.dumps(data)

        # 2. Fallback till IMAP om DB är tom
        with get_mailbox() as mb:
            mb.folder.set(folder)
            msgs = list(mb.fetch(A(uid=uid)))
            if msgs:
                msg = msgs[0]
                body_html = msg.html or ""
                body_text = msg.text or ""
                
                # Uppdatera DB så vi slipper hämta nästa gång
                atts_data = []
                for a in msg.attachments:
                     if not a.content_id and not (a.content_disposition == 'inline'):
                        atts_data.append({'filename': a.filename or "noname", 'size': a.size, 'content_type': a.content_type})
                
                with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                    conn.execute("UPDATE emails SET body=?, html=?, attachments=? WHERE uid=? AND folder=?", 
                                (body_text, body_html, json.dumps(atts_data), uid, folder))
                
                data = process_msg_data(body_html, body_text, attachments_list=msg.attachments)
                data['subject'] = msg.subject
                data['from'] = msg.from_
                return json.dumps(data)
    except Exception as e:
        log_event(f"Fel vid hämtning av meddelande {uid}: {e}")
        return json.dumps({'error': str(e)})
    except Exception as e: return json.dumps({'error': str(e)})
    return json.dumps({'error': 'Not found'})

@app.route('/api/attachment/<uid>')
def download_attachment(uid):
    filename = request.args.get('filename')
    disposition = request.args.get('disposition', 'attachment')
    if not filename: return "Filnamn saknas"
    folder = request.args.get('folder', 'INBOX')
    if folder == 'STARRED':
        try:
            with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
                row = conn.execute("SELECT folder FROM emails WHERE uid=?", (uid,)).fetchone()
                if row: folder = row[0]
        except: pass

    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            msgs = list(mb.fetch(A(uid=uid)))
            if not msgs:
                return "Mailet hittades inte på servern."
            
            msg = msgs[0]
            
            def make_resp(att):
                safe_filename = (att.filename or "noname").replace('\r', '').replace('\n', '').replace('"', "'")
                # Skapa ASCII-säker version för legacy headers (förhindrar krasch med specialtecken)
                ascii_filename = safe_filename.encode('ascii', 'ignore').decode('ascii').strip()
                if not ascii_filename: ascii_filename = "attachment"
                
                # Skapa UTF-8 version för moderna webbläsare (RFC 5987)
                encoded_filename = urllib.parse.quote(safe_filename)
                
                return Response(att.payload, mimetype=att.content_type, 
                              headers={"Content-Disposition": f"{disposition}; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}"})

            for att in msg.attachments:
                if (att.filename or "noname") == filename:
                    return make_resp(att)
            
            # Fallback: Försök matcha utan att bry sig om gemener/versaler
            for att in msg.attachments:
                if (att.filename or "noname").replace('\r', '').replace('\n', '').lower().strip() == filename.replace('\r', '').replace('\n', '').lower().strip():
                    return make_resp(att)
            
            return "Bilagan hittades inte."
    except Exception as e: return f"Fel: {str(e)}"

@app.route('/api/mark_read/<path:uids>')
def mark_read(uids):
    folder = request.args.get('folder', 'INBOX')
    uid_list = [u.strip() for u in uids.split(',')]
    # Spara status lokalt
    update_local_status(folder, uid_list, True)
    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            mb.flag(uid_list, '\\Seen', True)
            return "OK"
    except Exception as e:
        log_event(f"Error marking read: {e}")
        return "Error"

@app.route('/api/toggle_star/<uid>')
def toggle_star(uid):
    folder = request.args.get('folder', 'INBOX')
    
    # Om vi är i STARRED-mappen, försök hitta den riktiga mappen för att uppdatera IMAP
    if folder == 'STARRED':
        if os.path.exists(STAR_STATUS_FILE):
            try:
                with open(STAR_STATUS_FILE) as f:
                    data = json.load(f)
                    for fldr, uids in data.items():
                        if str(uid) in uids and uids[str(uid)]:
                            folder = fldr
                            break
            except: pass

    starred = request.args.get('starred') == 'true'
    update_star_status(folder, uid, starred)
    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            if starred:
                mb.flag([uid], '\\Flagged', True)
            else:
                mb.flag([uid], '\\Flagged', False)
            return "OK"
    except Exception as e: return str(e)

@app.route('/api/create_folder', methods=['POST'])
def create_folder():
    name = request.form.get('name', '').strip()
    # Uppdatera lokal mapp-cache efter skapande
    icon = request.form.get('icon')
    if not name: return "No name"
    
    final_name = name
    try:
        log_event(f"Skapar mapp: {name}")
        with get_mailbox() as mb:
            # Detektera avgränsare och prefix
            delimiter = '.'
            has_inbox_prefix = False
            root_folders_count = 0
            try:
                folders = list(mb.folder.list())
                for f in folders:
                    if getattr(f, 'delim', None): delimiter = f.delim
                    if f.name.upper() == 'INBOX': continue
                    if f.name.upper().startswith(f'INBOX{delimiter}'): has_inbox_prefix = True
                    else: root_folders_count += 1
            except: pass

            # Om vi har mappar under INBOX, eller om vi inte har några andra rotmappar och avgränsaren är punkt (Loopia-stil)
            if (has_inbox_prefix or (root_folders_count == 0 and delimiter == '.')) and not name.upper().startswith(f'INBOX{delimiter}') and name.upper() != 'INBOX':
                final_name = f"INBOX{delimiter}{name}"

            try:
                mb.folder.create(final_name)
                try: 
                    time.sleep(0.2)
                    mb.folder.subscribe(final_name)
                    log_event(f"Prenumererade på: {final_name}")
                except Exception as e: log_event(f"Kunde inte prenumerera på {final_name}: {e}")
            except Exception as e:
                if final_name == name and ("nonexistent namespace" in str(e).lower() or "prefixed with: inbox" in str(e).lower() or "permission denied" in str(e).lower()):
                    final_name = f"INBOX{delimiter}{name}"
                    mb.folder.create(final_name)
                    try: 
                        time.sleep(0.2)
                        mb.folder.subscribe(final_name)
                        log_event(f"Prenumererade på: {final_name}")
                    except Exception as e: log_event(f"Kunde inte prenumerera på {final_name}: {e}")
                else:
                    raise e
        
        if icon:
            save_folder_icon(final_name, icon)
            
        time.sleep(1.0) # Ge servern tid att registrera mappen
        
        # Kör en full prenumerations-synk i bakgrunden för säkerhets skull
        threading.Thread(target=sync_folder_structure, daemon=True).start()
        threading.Thread(target=subscribe_worker, daemon=True).start()
        return "OK"
    except Exception as e:
        log_event(f"Error creating folder: {e}")
        return str(e)

support_tunnel_url = None

@app.route('/api/support/start', methods=['POST'])
def start_support():
    global support_tunnel_url
    if not ngrok:
        return "Support-modul saknas (pyngrok)."
    
    if support_tunnel_url:
        return support_tunnel_url

    try:
        # Konfigurera auth token
        settings = load_settings()
        token = settings.get('ngrok_token')
        if token:
            ngrok.set_auth_token(token)
        else:
            return get_translations().get('ngrok_missing', 'Ngrok Authtoken saknas.')

        # Hämta porten som appen körs på
        port = app.config.get('SERVER_PORT', 80)
        # Starta tunnel (http protokoll till lokal port)
        
        # Använd 127.0.0.1 explicit. Eftersom vi binder till 0.0.0.0 fungerar localhost alltid,
        # och det undviker problem med IPv6 [::1] eller externa Docker-IPs som blockeras.
        tunnel = ngrok.connect(f"127.0.0.1:{port}")
        support_tunnel_url = tunnel.public_url
        log_event(f"Remote support startad: {support_tunnel_url}")
        return support_tunnel_url
    except Exception as e:
        return f"Fel vid start av support: {str(e)}"

@app.route('/api/support/stop', methods=['POST'])
def stop_support():
    global support_tunnel_url
    if not ngrok: return "Modul saknas"
    try:
        ngrok.kill()
        support_tunnel_url = None
        log_event("Remote support avslutad")
        return "OK"
    except Exception as e: return str(e)

@app.route('/api/save_ngrok_token', methods=['POST'])
def save_ngrok_token():
    token = request.form.get('token', '').strip()
    settings = load_settings()
    settings['ngrok_token'] = token
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    return "OK"

@app.route('/api/delete_folder', methods=['POST'])
def delete_folder():
    name = request.form.get('name')
    if not name: return "No name"
    try:
        log_event(f"Raderar mapp: {name}")
        with get_mailbox() as mb:
            mb.folder.delete(name)
        
        # Ta bort ikon-mappning om den finns
        icons = get_folder_icons_map()
        if name in icons:
            del icons[name]
            with open(FOLDER_ICONS_FILE, 'w') as f: json.dump(icons, f)
        
        threading.Thread(target=sync_folder_structure, daemon=True).start()
            
        return "OK"
    except Exception as e:
        log_event(f"Error deleting folder: {e}")
        return str(e)

@app.route('/api/sync_folders', methods=['POST'])
def sync_folders_api():
    threading.Thread(target=subscribe_worker, daemon=True).start()
    return "OK"

@app.route('/api/mark_unread/<path:uids>')
def mark_unread(uids):
    folder = request.args.get('folder', 'INBOX')
    uid_list = [u.strip() for u in uids.split(',')]
    # Spara status lokalt
    update_local_status(folder, uid_list, False)
    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            mb.flag(uid_list, '\\Seen', False)
            return "OK"
    except Exception as e:
        log_event(f"Error marking unread: {e}")
        return "Error"

@app.route('/api/move_mail', methods=['POST'])
def move_mail():
    folder = request.form.get('folder', 'INBOX')
    uids = request.form.get('uids')
    dest = request.form.get('dest')
    if not uids or not dest: return "Missing args"
    
    # Filtrera bort ogiltiga UIDs
    uid_list = [u for u in uids.split(',') if u.strip() and u not in ['0', 'None', 'undefined']]
    if not uid_list: return "No valid UIDs"

    log_event(f"Flyttar {len(uid_list)} mail från {folder} till {dest}")
    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            try:
                mb.move(uid_list, dest)
            except:
                # Fallback: Om MOVE misslyckas, kör COPY + DELETE (säkrare på vissa servrar)
                mb.copy(uid_list, dest)
                mb.delete(uid_list)
                try: mb.expunge()
                except: pass
            
        # Uppdatera lokal databas: Flytta mailen till nya mappen direkt (visuellt direkt)
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            placeholders = ','.join('?' * len(uid_list))
            # Uppdatera mappen för mailen. Om UID krockar i destinationen, ignorera (tas bort nedan)
            conn.execute(f"UPDATE OR IGNORE emails SET folder=? WHERE folder=? AND uid IN ({placeholders})", [dest, folder] + uid_list)
            # Städa bort från gamla mappen (om de inte flyttades pga krock eller annat)
            conn.execute(f"DELETE FROM emails WHERE folder=? AND uid IN ({placeholders})", [folder] + uid_list)
            
        # Starta synk av destinationen för att korrigera UIDs
        threading.Thread(target=sync_worker, args=(dest,), daemon=True).start()
            
        return "OK"
    except Exception as e: return str(e)

@app.route('/api/delete_mails', methods=['POST'])
def delete_mails():
    folder = request.form.get('folder', 'INBOX')
    uids = request.form.getlist('uids[]')
    if not uids: return "No UIDs"
    
    log_event(f"Raderar {len(uids)} mail från {folder}")
    
    trash_folder = None
    moved_to_trash = False

    # Försök ta bort från servern
    try:
        with get_mailbox() as mb:
            # Hitta papperskorg först
            try:
                folders = mb.folder.list()
                for f in folders:
                    if f.name in ['INBOX.Trash', 'Trash', 'Papperskorg', 'INBOX.Papperskorg', 'Deleted Items', 'Deleted Messages']:
                        trash_folder = f.name
                        break
                if not trash_folder:
                    for f in folders:
                        if 'trash' in f.name.lower() or 'papperskorg' in f.name.lower() or 'bin' in f.name.lower() or 'deleted' in f.name.lower():
                            trash_folder = f.name
                            break
            except: pass

            # Välj mappen vi ska radera från
            mb.folder.set(folder)
            
            # Filtrera bort ogiltiga UIDs
            valid_uids = [u for u in uids if u and u not in ['0', 'None', 'undefined']]
            
            if valid_uids:
                # Om vi inte är i papperskorgen och en papperskorg finns -> Flytta dit
                if trash_folder and folder != trash_folder:
                    try:
                        mb.move(valid_uids, trash_folder)
                        moved_to_trash = True
                    except:
                        # Fallback: Om flytt misslyckas, ta bort direkt
                        try: 
                            mb.copy(valid_uids, trash_folder)
                            mb.delete(valid_uids)
                            moved_to_trash = True
                        except: 
                            try: mb.delete(valid_uids)
                            except: pass
                else:
                    try: mb.delete(valid_uids)
                    except: pass
                
                # Tvinga servern att utföra raderingen permanent (ta bort mail markerade som \Deleted)
                try: mb.expunge()
                except: pass
    except Exception as e: log_event(f"IMAP delete error: {e}")
    
    # Ta bort från lokal databas direkt (även om IMAP misslyckades)
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            placeholders = ','.join('?' * len(uids))
            conn.execute(f"DELETE FROM emails WHERE folder=? AND uid IN ({placeholders})", [folder] + uids)
            
            # Specialstädning: Om vi försökte ta bort UID 0 eller None, rensa alla trasiga rader
            if '0' in uids or 'None' in uids or 'undefined' in uids or '' in uids:
                conn.execute("DELETE FROM emails WHERE folder=? AND (uid=0 OR uid IS NULL)", (folder,))
            
        # Om vi flyttade till papperskorgen, synka den så mailen dyker upp där
        if moved_to_trash and trash_folder:
            threading.Thread(target=sync_worker, args=(trash_folder,), daemon=True).start()
            
        return "OK"
    except Exception as e: return str(e)

@app.route('/api/empty_trash', methods=['POST'])
def empty_trash():
    folder = request.form.get('folder')
    if not folder: return "No folder"
    
    log_event(f"Tömmer papperskorgen: {folder}")
    try:
        with get_mailbox() as mb:
            mb.folder.set(folder)
            # Radera alla mail i mappen
            uids = mb.uids()
            if uids:
                mb.delete(uids)
                try: mb.expunge()
                except: pass
        
        # Rensa databasen
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.execute("DELETE FROM emails WHERE folder=?", (folder,))
            
        return "OK"
    except Exception as e: return str(e)

@app.route('/api/block_sender', methods=['POST'])
def block_sender():
    sender = request.form.get('sender')
    if not sender: return "No sender"
    
    # Rensa avsändare (ta bort namn, behåll email)
    if '<' in sender:
        try: sender = sender.split('<')[1].strip('>')
        except: pass
    log_event(f"Blockerar avsändare: {sender}")
    add_spam_sender(sender.strip())
    threading.Thread(target=move_existing_spam, args=(sender.strip(),), daemon=True).start()
    return "OK"

@app.route('/api/mark_as_ad', methods=['POST'])
def mark_as_ad():
    sender = request.form.get('sender')
    if not sender: return "No sender"
    
    # Rensa avsändare
    if '<' in sender:
        try: sender = sender.split('<')[1].strip('>')
        except: pass
    log_event(f"Markerar som reklam: {sender}")
    add_ad_sender(sender.strip())
    threading.Thread(target=move_existing_ads, args=(sender.strip(),), daemon=True).start()
    return "OK"

@app.route('/api/whitelist_sender', methods=['POST'])
def whitelist_sender():
    sender = request.form.get('sender')
    if not sender: return "No sender"
    
    # Rensa avsändare
    if '<' in sender:
        try: sender = sender.split('<')[1].strip('>')
        except: pass
    log_event(f"Vitlistar avsändare: {sender}")
    add_whitelist_sender(sender.strip())
    return "OK"

@app.route('/api/available_icons')
def available_icons():
    icon_dir = os.path.join(app.static_folder, 'ikoner', 'folder')
    if not os.path.exists(icon_dir): return json.dumps([])
    files = [f for f in os.listdir(icon_dir) if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.svg'))]
    return json.dumps(files)

@app.route('/api/search_suggestions')
def search_suggestions():
    query = request.args.get('q', '').strip()
    folder = request.args.get('folder', 'INBOX')
    if not query or len(query) < 2: return json.dumps([])
    
    # Starta synk om det inte redan körs
    threading.Thread(target=sync_worker, args=(folder,), daemon=True).start()
    
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            clean_query = query.replace('"', '').strip()
            if not clean_query: return json.dumps([])
            fts_query = f'{clean_query}*'
            rows = conn.execute("SELECT subject, sender, date_str FROM emails WHERE rowid IN (SELECT rowid FROM emails_fts WHERE emails_fts MATCH ? ORDER BY rank) ORDER BY date_iso DESC LIMIT 5", (fts_query,)).fetchall()
            suggestions = []
            for row in rows:
                suggestions.append({'subject': row['subject'], 'from': row['sender'], 'date': row['date_str']})
            return json.dumps(suggestions)
    except:
        return json.dumps([])

@app.route('/api/contact_suggestions')
def contact_suggestions():
    query = request.args.get('q', '').strip()
    if not query: return json.dumps([])
    
    suggestions = []
    try:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            
            # 1. Sök i Kontaktboken (Prioriterat)
            c_rows = conn.execute("SELECT name, email FROM contacts WHERE name LIKE ? OR email LIKE ? LIMIT 5", (f'%{query}%', f'%{query}%')).fetchall()
            for r in c_rows:
                display = f"{r['name']} <{r['email']}>" if r['name'] else r['email']
                suggestions.append(display)

            # 2. Sök i Mailhistorik
            e_rows = conn.execute("SELECT DISTINCT sender FROM emails WHERE sender LIKE ? LIMIT 10", (f'%{query}%',)).fetchall()
            for r in e_rows:
                if r['sender'] and r['sender'] not in suggestions:
                    suggestions.append(r['sender'])
            
            return json.dumps(suggestions[:10])
    except:
        return json.dumps([])

@app.route('/api/contacts', methods=['GET', 'POST'])
def handle_contacts():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        if not email: return "Email required"
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.execute("INSERT OR REPLACE INTO contacts (name, email) VALUES (?, ?)", (name, email))
        return "OK"
    else:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
            return json.dumps([dict(r) for r in rows])

@app.route('/api/contacts/delete', methods=['POST'])
def delete_contact():
    id = request.form.get('id')
    with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
        conn.execute("DELETE FROM contacts WHERE id=?", (id,))
    return "OK"

@app.route('/api/rules', methods=['GET', 'POST'])
def handle_rules():
    if request.method == 'POST':
        keyword = request.form.get('keyword', '').strip()
        folder = request.form.get('folder', '').strip()
        field = request.form.get('field', 'subject').strip()
        if not keyword or not folder: return "Missing args"
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.execute("INSERT INTO rules (keyword, target_folder, check_field) VALUES (?, ?, ?)", (keyword, folder, field))
        return "OK"
    else:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM rules").fetchall()
            return json.dumps([dict(r) for r in rows])

@app.route('/api/rules/delete', methods=['POST'])
def delete_rule():
    id = request.form.get('id')
    with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
        conn.execute("DELETE FROM rules WHERE id=?", (id,))
    return "OK"

@app.route('/api/labels', methods=['GET', 'POST'])
def handle_labels():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        color = request.form.get('color', '#3b82f6').strip()
        keyword = request.form.get('keyword', '').strip()
        field = request.form.get('field', 'subject').strip()
        if not name or not keyword: return "Missing args"
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.execute("INSERT INTO labels (name, color, keyword, check_field) VALUES (?, ?, ?, ?)", (name, color, keyword, field))
        threading.Thread(target=apply_labels_to_all, daemon=True).start()
        return "OK"
    else:
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM labels").fetchall()
            return json.dumps([dict(r) for r in rows])

@app.route('/api/labels/delete', methods=['POST'])
def delete_label():
    id = request.form.get('id')
    with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
        conn.execute("DELETE FROM labels WHERE id=?", (id,))
    return "OK"

@app.route('/api/assign_label', methods=['POST'])
def assign_label():
    try:
        label_id = int(request.form.get('label_id'))
        uids_str = request.form.get('uids')
        if not uids_str: return "No UIDs"
        uids = [u.strip() for u in uids_str.split(',') if u.strip()]
        
        with sqlite3.connect(DB_FILE, timeout=30.0) as conn:
            placeholders = ','.join('?' * len(uids))
            rows = conn.execute(f"SELECT uid, folder, labels FROM emails WHERE uid IN ({placeholders})", uids).fetchall()
            
            updates = []
            for r in rows:
                uid, folder, lbls_json = r
                try:
                    lbls = json.loads(lbls_json) if lbls_json else []
                except: lbls = []
                
                if label_id not in lbls:
                    lbls.append(label_id)
                    updates.append((json.dumps(lbls), uid, folder))
            
            if updates:
                conn.executemany("UPDATE emails SET labels=? WHERE uid=? AND folder=?", updates)
        return "OK"
    except Exception as e: return str(e)

@app.route('/api/save_draft', methods=['POST'])
def save_draft():
    cfg = load_settings()
    try:
        msg = MIMEMultipart()
        msg['Subject'] = request.form.get('subject')
        msg['From'] = cfg['email']
        msg['To'] = request.form.get('to')
        msg['Date'] = formatdate(localtime=True)
        
        log_event("Sparar utkast")
        body = (request.form.get('body') or "").replace('\n','<br>')
        msg.attach(MIMEText(body, 'html'))

        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if f.filename:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{f.filename}"')
                    msg.attach(part)

        with get_mailbox() as mb:
            draft_folder = None
            for f in mb.folder.list():
                if 'draft' in f.name.lower() or 'utkast' in f.name.lower():
                    draft_folder = f.name
                    break
            
            if not draft_folder:
                draft_folder = 'INBOX.Drafts' # Fallback

            try:
                mb.append(msg.as_bytes(), draft_folder, flag_set=['\\Draft', '\\Seen'])
                threading.Thread(target=sync_worker, args=(draft_folder,), daemon=True).start()
                return "Saved"
            except: return "Error saving draft"
    except Exception as e: return str(e)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    settings = {
        'email': request.form.get('email', '').strip(),
        'password': request.form.get('password', '').strip(),
        'imap_server': request.form.get('imap_server', '').strip(),
        'imap_port': request.form.get('imap_port', '993').strip(),
        'smtp_server': request.form.get('smtp_server', '').strip(),
        'smtp_port': request.form.get('smtp_port', '587').strip(),
        'signature': request.form.get('signature', ''),
        'web_password': request.form.get('web_password', '').strip(),
        'layout': request.form.get('layout', 'normal'),
        'language': request.form.get('language', 'sv')
    }
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4)
    return redirect(url_for('index'))

@app.route('/send', methods=['POST'])
def send():
    cfg = load_settings()
    try:
        msg = MIMEMultipart()
        msg['Subject'] = request.form.get('subject')
        msg['From'] = cfg['email']
        msg['To'] = request.form.get('to')
        msg['Date'] = formatdate(localtime=True)
        body = request.form.get('body') or ""
        log_event(f"Skickar mail till {msg['To']}")
        parts = []
        
        # Hantera vidarebefordrade filer
        forward_uid = request.form.get('forward_uid')
        folder = request.form.get('folder')
        forward_files = request.form.getlist('forward_files')

        if forward_uid and folder:
            try:
                with get_mailbox() as mb:
                    mb.folder.set(folder)
                    # Hämta mailet med specifikt UID
                    msgs = list(mb.fetch(A(uid=str(forward_uid))))
                    if msgs:
                        orig_msg = msgs[0]
                        for att in orig_msg.attachments:
                            fname = att.filename or "noname"


                            # Beräkna CID och placeholders
                            cid = (att.content_id or "").strip('<>')
                            if not cid:
                                cid = f"{hashlib.md5(fname.encode()).hexdigest()}@zalaso"
                            
                            placeholder_image = f'[image: {fname}]'
                            placeholder_cid = f'[cid:{cid}]'
                            
                            # Kontrollera om filen ska vidarebefordras (finns i listan ELLER refereras i texten)
                            should_attach = fname in forward_files or placeholder_image in body or placeholder_cid in body
                            
                            if should_attach:
                                try:
                                    ctype = att.content_type or 'application/octet-stream'
                                    maintype, subtype = ctype.split('/', 1) if '/' in ctype else ('application', 'octet-stream')
                                    part = MIMEBase(maintype, subtype)
                                    part.set_payload(att.payload)
                                    encoders.encode_base64(part)
                                    
                                    # Kolla om bilden är webbsäker (kan visas i webbläsare/mailklienter)
                                    is_web_image = maintype == 'image' and subtype.lower() in ['jpeg', 'jpg', 'png', 'gif', 'webp']
                                    
                                    is_inline = False
                                    
                                    # Ersätt placeholders med riktiga bild-taggar
                                    if placeholder_image in body:
                                        body = body.replace(placeholder_image, f'<img src="cid:{cid}" alt="{fname}" style="max-width:100%">')
                                        is_inline = True
                                    
                                    if placeholder_cid in body:
                                        body = body.replace(placeholder_cid, f'<img src="cid:{cid}" alt="{fname}" style="max-width:100%">')
                                        is_inline = True
                                    
                                    if is_web_image and not is_inline:
                                        # Om det är en bild som ska med, men ingen placeholder hittades/ersattes, lägg till den sist
                                        body += f'<br><br><img src="cid:{cid}" alt="{fname}" style="max-width:100%"><br>'
                                        is_inline = True
                                    
                                    part.add_header('Content-ID', f'<{cid}>')
                                    if is_inline:
                                        part.add_header('Content-Disposition', f'inline; filename="{fname}"')
                                    else:
                                        part.add_header('Content-Disposition', f'attachment; filename="{fname}"')
                                    
                                    parts.append(part)
                                except Exception as e:
                                    log_event(f"Error attaching forwarded file {fname}: {e}")
                            
            except Exception as e:
                log_event(f"Forward error: {e}")

        if 'files' in request.files:
            for f in request.files.getlist('files'):
                if f.filename:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="{f.filename}"')
                    parts.append(part)

        body += "<br><br>--<br>Skickat från Zalaso Mail"
        msg.attach(MIMEText(body, 'html'))
        
        for p in parts:
            msg.attach(p)

        # Hantera SSL/TLS korrekt och lägg till timeout
        timeout = 30
        smtp_port = int(cfg['smtp_port'])
        if smtp_port == 465:
            s = smtplib.SMTP_SSL(cfg['smtp_server'], smtp_port, timeout=timeout)
        else:
            s = smtplib.SMTP(cfg['smtp_server'], smtp_port, timeout=timeout)
            try: s.starttls()
            except: pass

        s.login(cfg['email'], cfg['password'])
        s.send_message(msg)
        s.quit()
        log_event("Mail skickat")

        # Spara i Skickat-mappen
        with get_mailbox() as mb:
            sent_folder = None
            folders = mb.folder.list()
            # Prioritera exakta matchningar
            for f in folders:
                if f.name in ['INBOX.Sent', 'Sent', 'Skickat', 'INBOX.Skickat', 'Sent Items']:
                    sent_folder = f.name
                    break
                for f in folders:
                    if 'sent' in f.name.lower() or 'skickat' in f.name.lower():
                        sent_folder = f.name
                        break
            
            if not sent_folder: sent_folder = 'INBOX.Sent'
            
            try:
                mb.append(msg.as_bytes(), sent_folder, flag_set=['\\Seen'])
            except:
                # Om mappen inte finns, försök skapa den och spara igen
                try:
                    mb.folder.create(sent_folder)
                    mb.append(msg.as_bytes(), sent_folder, flag_set=['\\Seen'])
                except: pass

    except: pass
    return redirect(url_for('index'))

@app.route('/api/get_filters')
def get_filters_api():
    return json.dumps(get_spam_filters())

@app.route('/api/send_logs', methods=['POST'])
def send_logs():
    cfg = load_settings()
    if not cfg.get('email') or not cfg.get('password'):
        return "Inga kontouppgifter konfigurerade"
    
    smtp_server = cfg.get('smtp_server')
    try: smtp_port = int(cfg.get('smtp_port', 587))
    except: return "Ogiltig SMTP-port"

    if not smtp_server: return "SMTP-server saknas"
    
    try:
        if not os.path.exists(LOG_FILE): return "Ingen loggfil hittades"
        
        # Begränsa loggstorlek till 2MB för att undvika timeout
        file_size = os.path.getsize(LOG_FILE)
        with open(LOG_FILE, 'rb') as f:
            if file_size > 2 * 1024 * 1024:
                f.seek(-2 * 1024 * 1024, 2)
                log_data = b"... [TRUNCATED] ...\n" + f.read()
            else:
                log_data = f.read()

        msg = MIMEMultipart()
        msg['Subject'] = f"Zalaso Logg - {cfg['email']}"
        msg['From'] = cfg['email']
        msg['To'] = "securecode95@gmail.com"
        msg['Date'] = formatdate(localtime=True)
        
        msg.attach(MIMEText("Här är loggfilen från Zalaso Mail.", 'plain'))
        
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(log_data)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="zalaso.log"')
        msg.attach(part)

        # Hantera SSL/TLS korrekt och lägg till timeout
        timeout = 30
        if smtp_port == 465:
            s = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=timeout)
        else:
            s = smtplib.SMTP(smtp_server, smtp_port, timeout=timeout)
            try: s.starttls()
            except: pass

        s.login(cfg['email'], cfg['password'])
        s.send_message(msg)
        s.quit()
        return "OK"
    except Exception as e: return f"Fel: {str(e)}"

@app.route('/api/logs')
def get_logs_api():
    if not os.path.exists(LOG_FILE): return json.dumps([])
    try:
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
            return json.dumps([l.strip() for l in lines[-100:][::-1]])
    except: return json.dumps([])

@app.route('/api/restart', methods=['POST'])
def restart_server():
    log_event("Startar om servern...")
    def restart():
        time.sleep(1)
        os._exit(1)
    threading.Thread(target=restart).start()
    return "OK"

@app.route('/api/test_connection', methods=['POST'])
def test_connection():
    email = request.form.get('email')
    password = request.form.get('password')
    server = request.form.get('imap_server')
    port = request.form.get('imap_port')
    
    if not all([email, password, server, port]):
        return "Fyll i alla fält för IMAP."
        
    try:
        ctx = ssl.create_default_context()
        if 'zalaso' in server: ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        with MailBox(server, port=int(port), ssl_context=ctx).login(email, password):
            return "OK"
    except Exception as e: return str(e)

if __name__ == '__main__':
    init_db()
    
    is_frozen = getattr(sys, 'frozen', False)
    host = '0.0.0.0'
    # Stäng av debug för att undvika problem med reloader/dubbla processer i Docker + ngrok
    debug = False
    
    # Försök binda till port 80, annars fall tillbaka till 5000
    port = 80
    try:
        test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        test_sock.bind((host, 80))
        test_sock.close()
    except:
        port = 5000
        
    def open_browser():
        try: 
            url = 'http://127.0.0.1' if port == 80 else f'http://127.0.0.1:{port}'
            webbrowser.open(url)
        except: pass
    threading.Timer(1.5, open_browser).start()
    
    print(f"Startar Zalaso Mail på port {port}...")
    app.config['SERVER_PORT'] = port
    app.run(host=host, port=port, debug=debug)
