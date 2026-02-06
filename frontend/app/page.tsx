"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import Image from "next/image";
import LeaAvatar from "./lea.jpg";
import FileSlot from "../components/FileSlot";

type Msg = {
    role: "user" | "assistant";
    content: string;
};

function TypingDots() {
    return (
        <div className="flex items-center gap-1">
            <motion.span
                className="h-1.5 w-1.5 rounded-full bg-gray-400"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity }}
            />
            <motion.span
                className="h-1.5 w-1.5 rounded-full bg-gray-400"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.15 }}
            />
            <motion.span
                className="h-1.5 w-1.5 rounded-full bg-gray-400"
                animate={{ opacity: [0.3, 1, 0.3] }}
                transition={{ duration: 1, repeat: Infinity, delay: 0.3 }}
            />
        </div>
    );
}

function classifyIntent(text: string): string {
    const t = (text || "").toLowerCase();
    
    // Rental/Location (FR / EN / AR)
    if (
        // French
        t.includes("location") ||
        t.includes("louer") ||
        t.includes("je veux louer") ||
        t.includes("je souhaite louer") ||
        t.includes("tire-lait") ||
        t.includes("tire lait") ||
        t.includes("tirelait") ||
        // English
        t.includes("rental") ||
        t.includes("rent") ||
        t.includes("breast pump") ||
        t.includes("i want to rent") ||
        t.includes("i would like to rent") ||
        // Arabic
        t.includes("استئجار") ||
        t.includes("تأجير") ||
        t.includes("شفاط") ||
        t.includes("أريد استئجار") ||
        t.includes("أود استئجار")
    ) {
        return "rent";
    }
    
    // Renewal (FR / EN / AR)
    if (
        // French
        t.includes("renouvellement") ||
        t.includes("prolongation") ||
        t.includes("renouveler") ||
        t.includes("prolonger") ||
        t.includes("je veux renouveler") ||
        t.includes("je souhaite renouveler") ||
        // English
        t.includes("renewal") ||
        t.includes("renew") ||
        t.includes("extend") ||
        t.includes("extension") ||
        t.includes("i want to renew") ||
        t.includes("i would like to renew") ||
        // Arabic
        t.includes("تجديد") ||
        t.includes("تمديد") ||
        t.includes("أريد تجديد") ||
        t.includes("أود تجديد")
    ) {
        return "renew";
    }
    
    // Return (FR / EN / AR)
    if (
        // French
        t.includes("retour") ||
        t.includes("rendre") ||
        t.includes("restituer") ||
        t.includes("étiquette retour") ||
        t.includes("etiquette retour") ||
        t.includes("chronopost") ||
        t.includes("je veux retourner") ||
        t.includes("je souhaite retourner") ||
        t.includes("renvoyer") ||
        // English
        t.includes("return") ||
        t.includes("send back") ||
        t.includes("return item") ||
        t.includes("i want to return") ||
        t.includes("i would like to return") ||
        // Arabic
        t.includes("إرجاع") ||
        t.includes("رجوع") ||
        t.includes("إعادة") ||
        t.includes("أريد إرجاع") ||
        t.includes("أود إرجاع")
    ) {
        return "return";
    }
    
    return "other";
}

function isRentalTrigger(text: string) {
    return classifyIntent(text) === "rent";
}

function assistantAsksAttachments(text: string) {
    const t = (text || "").toLowerCase();
    // Detect explicit request for the two files just before confirmation
    // FR
    const fr = (
        t.includes("ajoutez les 2 pièces") ||
        t.includes("ajoutez les deux pièces") ||
        ((t.includes("ordonnance") || t.includes("carte mutuelle") || t.includes("mutuelle")) && (t.includes("ajoutez") || t.includes("merci d'")))
    );
    // EN
    const en = (
        t.includes("attach both files") ||
        ((t.includes("prescription") || t.includes("insurance")) && (t.includes("attach") || t.includes("please attach")))
    );
    // AR
    const ar = (
        (t.includes("أرفق") || t.includes("يرجى إرفاق")) && (t.includes("الوصفة") || t.includes("بطاقة التأمين"))
    );
    return fr || en || ar;
}

export default function Page() {
    const UI = useMemo(() => ({
        fr: {
            greeting:
                "Salut 👋 Je suis LEA, le chatbot Tire-Lait Express.\n\nComment puis-je vous aider aujourd’hui ?",
            lang: "Langue",
            reset: "Réinitialiser",
            inputPlaceholder: "Écrivez votre message... (Shift+Entrée pour aller à la ligne)",
            quick: ["Bonjour"],
            intents: ["Location", "Renouvellement", "Retour"],
            attachments: "Pièces jointes",
            tip: "Ajoute les 2 fichiers avant de confirmer : ordonnance + carte mutuelle.",
            prescription: "Ordonnance",
            insurance: "Mutuelle",
            requiredDot: "• obligatoire",
            fileNone: "Aucun fichier",
            fileRemove: "Retirer",
            fileAdd: "Ajouter",
            fileReplace: "Remplacer",
            fileHint: "PDF / photo",
            send: "Envoyer",
            qa: "Question/Aide",
            qaNoAnswer: "Aucune réponse trouvée dans la base.",
            qaPrompt: "Comment puis-je vous aider ? Posez votre question.",
        },
        en: {
            greeting:
                "Hi 👋 I’m LEA, the Tire-Lait Express chatbot.\n\nHow can I help you today?",
            lang: "Language",
            reset: "Reset",
            inputPlaceholder: "Type your message... (Shift+Enter for new line)",
            quick: ["Hello"],
            intents: ["Rental", "Renewal", "Return"],
            attachments: "Attachments",
            tip: "Add both files before confirming: prescription + insurance card.",
            prescription: "Prescription",
            insurance: "Insurance",
            requiredDot: "• required",
            fileNone: "No file",
            fileRemove: "Remove",
            fileAdd: "Add",
            fileReplace: "Replace",
            fileHint: "PDF / photo",
            send: "Send",
            qa: "Question/Help",
            qaNoAnswer: "No answer found in the knowledge base.",
            qaPrompt: "How can I help you? Please type your question.",
        },
        ar: {
            greeting:
                "مرحبًا 👋 أنا ليا، شاتبوت Tire-Lait Express.\n\nكيف يمكنني مساعدتك اليوم؟",
            lang: "اللغة",
            reset: "إعادة ضبط",
            inputPlaceholder: "اكتب رسالتك... (Shift+Enter للسطر الجديد)",
            quick: ["مرحبًا"],
            intents: ["استئجار", "تجديد", "إرجاع"],
            attachments: "المرفقات",
            tip: "أضف الملفين قبل التأكيد: الوصفة + بطاقة التأمين.",
            prescription: "الوصفة الطبية",
            insurance: "بطاقة التأمين",
            requiredDot: "• إلزامي",
            fileNone: "لا يوجد ملف",
            fileRemove: "إزالة",
            fileAdd: "إضافة",
            fileReplace: "استبدال",
            fileHint: "PDF / صورة",
            send: "إرسال",
            qa: "سؤال/مساعدة",
            qaNoAnswer: "لا توجد إجابة في قاعدة المعرفة.",
            qaPrompt: "كيف يمكنني مساعدتك؟ اكتب سؤالك من فضلك.",
        },
    }), []);

    // Pas de langue forcée par défaut pour laisser la détection serveur agir
    const [language, setLanguage] = useState<string>("");
    const ui = UI[(language as "fr" | "en" | "ar") || "fr"];
    const isRTL = language === "ar";

    const [messages, setMessages] = useState<Msg[]>([
        { role: "assistant", content: ui.greeting },
    ]);
    const [input, setInput] = useState("");
    const [loading, setLoading] = useState(false);

    const [open, setOpen] = useState(false);
    const [sessionId, setSessionId] = useState<string>("");

    const [prescriptionFile, setPrescriptionFile] = useState<File | null>(null);
    const [insuranceFile, setInsuranceFile] = useState<File | null>(null);

    // ✅ Mode location + affichage PJ uniquement si nécessaire
    const [rentalMode, setRentalMode] = useState(false);
    const [attachmentsVisible, setAttachmentsVisible] = useState(false);
    const [attachmentsOpen, setAttachmentsOpen] = useState(false);

    const [showAttachTip, setShowAttachTip] = useState(false);
    const [qaMode, setQaMode] = useState(false);

    // Confirmation summary modal (after backend validates details)
    const [confirmOpen, setConfirmOpen] = useState(false);
    const [confirmSummary, setConfirmSummary] = useState<any | null>(null);
    const [confirmEdit, setConfirmEdit] = useState(false);
    const [editableSummary, setEditableSummary] = useState<any | null>(null);
    // Show attachments only at the very end (just before confirmation)
    const [awaitingFinalAttachments, setAwaitingFinalAttachments] = useState(false);

    const bottomRef = useRef<HTMLDivElement | null>(null);
    const textareaRef = useRef<HTMLTextAreaElement | null>(null);
    // Ensure the message box stays ready to type without clicking each time
    const focusComposer = () => requestAnimationFrame(() => textareaRef.current?.focus());

    useEffect(() => {
        const key = "tlx_session_id";
        const existing = localStorage.getItem(key);
        if (existing) {
            setSessionId(existing);
        } else {
            const id = crypto.randomUUID();
            localStorage.setItem(key, id);
            setSessionId(id);
        }
    }, []);

    useEffect(() => {
        if (!open) return;
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [messages, loading, open]);

    useEffect(() => {
        if (open) setTimeout(() => textareaRef.current?.focus(), 150);
    }, [open]);

    const filesCount = (prescriptionFile ? 1 : 0) + (insuranceFile ? 1 : 0);

    // ✅ optionnel : quand les 2 fichiers sont présents, on replie automatiquement pour gagner de la place
    useEffect(() => {
        if (!attachmentsVisible) return;
        if (filesCount >= 2) {
            setAttachmentsOpen(false);
        }
    }, [filesCount, attachmentsVisible]);

    async function sendMessage(textOverride?: string) {
        const text = (textOverride ?? input).trim();
        const hasAttachToSend = Boolean(prescriptionFile || insuranceFile);
        if (loading) return;
        if (!sessionId) return;

        // Allow sending when only attachments are provided (no text)
        if (!text && !hasAttachToSend) return;

        // ✅ si l’utilisateur déclenche la location, on passe en rentalMode
        if (isRentalTrigger(text)) {
            setQaMode(false);
            setRentalMode(true);
        }

        const userMsg: Msg = { role: "user", content: text || (language === "en" ? "Documents uploaded" : language === "ar" ? "تم رفع المستندات" : "Documents envoyés") };
        const nextMessages = [...messages, userMsg];

        setMessages(nextMessages);
        setInput("");
        setLoading(true);

        try {
            // QA mode: answer only from CSV RAG
            if (qaMode) {
                const formR = new FormData();
                formR.append("q", text);
                if (language) formR.append("language", language);
                // Request RAG + LLM generation for QA (fallback=true)
                formR.append("fallback", "true");
                const resR = await fetch("http://127.0.0.1:8000/rag/ask", { method: "POST", body: formR });
                const dataR = await resR.json();
                if (dataR.lang && !language) setLanguage(dataR.lang as string);
                const ans = (dataR.answer as string) || ui.qaNoAnswer;
                setMessages((prev) => [...prev, { role: "assistant", content: ans }]);
                return;
            }
            const form = new FormData();
            form.append("messages", JSON.stringify(nextMessages));
            form.append("session_id", sessionId);
            if (language) form.append("language", language);

            if (prescriptionFile) form.append("prescription_file", prescriptionFile);
            if (insuranceFile) form.append("insurance_file", insuranceFile);

            const res = await fetch("http://127.0.0.1:8000/chat", {
                method: "POST",
                body: form,
            });

            const data = await res.json();

            // Aligner l'UI avec la langue renvoyée par le backend en mode auto
            if (data.lang && !language) {
                setLanguage(data.lang as string);
            }

            if (data.session_id && data.session_id !== sessionId) {
                setSessionId(data.session_id);
                localStorage.setItem("tlx_session_id", data.session_id);
            }

            const assistantMsg: Msg = { role: "assistant", content: data.reply };

            // Show the attachments bar only when the assistant explicitly asks for the two files (last step before confirmation)
            const askForAttachments = assistantAsksAttachments(assistantMsg.content) || (!!data.attachments && Array.isArray(data.attachments) && (data.attachments.length || 0) < 2 && (data.intent && ["rent","renew"].includes(data.intent)));
            setAttachmentsVisible(!!askForAttachments);
            if (askForAttachments) setAttachmentsOpen(true); else setAttachmentsOpen(false);

            // If backend asks for confirmation with a summary, open confirmation modal and avoid duplicating the recap in the chat feed
            if (data.confirm) {
                setConfirmSummary(data.summary || {});
                setEditableSummary({
                    name: data.summary?.name || "",
                    start_date: data.summary?.start_date || "",
                    end_date: data.summary?.end_date || "",
                    postal_code: data.summary?.postal_code || "",
                });
                setConfirmEdit(false);
                setConfirmOpen(true);
            } else {
                // Only append assistant message when it's not a confirmation summary
                setMessages((prev) => [...prev, assistantMsg]);
                setConfirmOpen(false);
                setConfirmSummary(null);
                setEditableSummary(null);
                setConfirmEdit(false);
            }
        } catch {
            setMessages((prev) => [
                ...prev,
                {
                    role: "assistant",
                    content:
                        "❌ Impossible de contacter le backend.\nVérifie que FastAPI tourne sur http://127.0.0.1:8000",
                },
            ]);
        } finally {
            setLoading(false);
            focusComposer();
        }
    }

    async function confirmOrder() {
        // If user edited fields inline, first send labeled updates, then auto confirm
        if (confirmEdit && editableSummary) {
            const labels = language === "en"
                ? { name: "Name", start: "Start date", end: "End date", pc: "Postal code" }
                : language === "ar"
                ? { name: "الاسم", start: "تاريخ البدء", end: "تاريخ النهاية", pc: "الرمز البريدي" }
                : { name: "Nom", start: "Date début", end: "Date fin", pc: "Code postal" };

            const lines = [
                `${labels.name}: ${editableSummary.name || ""}`,
                `${labels.start}: ${editableSummary.start_date || ""}`,
                `${labels.end}: ${editableSummary.end_date || ""}`,
                `${labels.pc}: ${editableSummary.postal_code || ""}`,
            ].join("\n");

            setConfirmOpen(false);
            setAwaitingFinalAttachments(false);
            await sendMessage(lines);
            const yes = language === "en" ? "yes" : language === "ar" ? "نعم" : "oui";
            await sendMessage(yes);
            setConfirmSummary(null);
            setEditableSummary(null);
            setConfirmEdit(false);
            return;
        }
        // Send a simple affirmative token based on language
        const yes = language === "en" ? "yes" : language === "ar" ? "نعم" : "oui";
        setConfirmOpen(false);
        setConfirmSummary(null);
        setEditableSummary(null);
        setConfirmEdit(false);
        setAwaitingFinalAttachments(false);
        sendMessage(yes);
        setTimeout(focusComposer, 50);
    }

    function cancelConfirm() {
        // Toggle inline edit mode without sending a chat message
        setConfirmEdit((v) => !v);
        setTimeout(focusComposer, 50);
    }

    function askFAQ() {
        // Enter QA mode: prompt the user, then subsequent messages use RAG-only
        if (loading) return;
        setQaMode(true);
        setRentalMode(false);
        setAttachmentsVisible(false);
        setAttachmentsOpen(false);
        setShowAttachTip(false);
        setMessages((prev) => [...prev, { role: "assistant", content: ui.qaPrompt }]);
        setTimeout(focusComposer, 50);
    }

    async function applyLanguage(newLang: string) {
        setLanguage(newLang);
        localStorage.setItem("tlx_lang", newLang);

        // Reset UI to localized greeting
        setMessages([{ role: "assistant", content: UI[newLang as "fr" | "en" | "ar"].greeting }]);
        setInput("");
        setPrescriptionFile(null);
        setInsuranceFile(null);
        setRentalMode(false);
        setAttachmentsVisible(false);
        setAttachmentsOpen(false);
        setShowAttachTip(false);
        setQaMode(false);

        // Optionnel: notifier le backend pour fixer la langue de session et recevoir un message de confirmation
        if (!sessionId) return;
        try {
            const form = new FormData();
            form.append("messages", JSON.stringify(messages));
            form.append("session_id", sessionId);
            form.append("language", newLang);
            const res = await fetch("http://127.0.0.1:8000/chat", { method: "POST", body: form });
            const data = await res.json();
            if (data?.reply) setMessages((prev) => [...prev, { role: "assistant", content: data.reply }]);
        } catch {}
        setTimeout(focusComposer, 50);
    }

    function clearChat() {
        setMessages([{ role: "assistant", content: ui.greeting }]);
        setInput("");
        setPrescriptionFile(null);
        setInsuranceFile(null);

        setRentalMode(false);
        setAttachmentsVisible(false);
        setAttachmentsOpen(false);
        setShowAttachTip(false);
        setQaMode(false);
        setAwaitingFinalAttachments(false);
        setTimeout(focusComposer, 50);
    }

    function onTextareaKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    }

    return (
        <div className="min-h-screen p-6" style={{ background: "var(--bg-page)" }}>
            {/* Page Demo */}
              <div className="max-w-3xl mx-auto rounded-2xl border p-6"
                  style={{ background: "var(--surface)", borderColor: "var(--surface-border)", boxShadow: "var(--shadow-soft)" }}>
                <h1 className="text-2xl font-bold tracking-tight">Page de démo</h1>
                <p className="mt-2" style={{ color: "var(--text-muted)" }}>
                    Cette page simule ton futur site PrestaShop. Le chatbot apparaît en bas
                    à droite comme un widget moderne.
                </p>

                <div className="mt-6 grid gap-4 sm:grid-cols-2">
                    <div className="p-4 rounded-2xl border shadow-sm hover:shadow-md transition" style={{ background: "var(--surface)", borderColor: "var(--surface-border)" }}>
                        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Produit</div>
                        <div className="font-semibold mt-1">Tire-lait</div>
                        <div className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                            Location & accessoires — livraison rapide.
                        </div>
                    </div>
                    <div className="p-4 rounded-2xl border shadow-sm hover:shadow-md transition" style={{ background: "var(--surface)", borderColor: "var(--surface-border)" }}>
                        <div className="text-sm" style={{ color: "var(--text-muted)" }}>Besoin d’aide ?</div>
                        <div className="font-semibold mt-1">Assistance</div>
                        <div className="text-sm mt-1" style={{ color: "var(--text-muted)" }}>
                            Clique sur la bulle en bas à droite.
                        </div>
                    </div>
                </div>
            </div>

            {/* Floating bubble */}
            <motion.button
                onClick={() => setOpen((v) => !v)}
                className="fixed bottom-6 right-6 h-14 w-14 rounded-full shadow-2xl text-white flex items-center justify-center"
                style={{
                    background: "var(--chat-header-gradient)",
                    boxShadow: "var(--ring), var(--shadow-float)"
                }}
                whileHover={{ scale: 1.06 }}
                whileTap={{ scale: 0.95 }}
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ type: "spring", stiffness: 400, damping: 20 }}
                aria-label="Ouvrir le chatbot"
            >
                <AnimatePresence mode="wait" initial={false}>
                    {!open ? (
                        <motion.div
                            key="open"
                            initial={{ rotate: -6, opacity: 0 }}
                            animate={{ rotate: 0, opacity: 1 }}
                            exit={{ rotate: 6, opacity: 0 }}
                            transition={{ duration: 0.18 }}
                                className="h-12 w-12 rounded-full overflow-hidden border-2 shadow"
                                style={{ borderColor: "var(--surface-border)" }}
                        >
                            <Image src={LeaAvatar} alt="LEA" className="h-full w-full object-cover" />
                        </motion.div>
                    ) : (
                        <motion.span
                            key="close"
                            initial={{ rotate: 10, opacity: 0 }}
                            animate={{ rotate: 0, opacity: 1 }}
                            exit={{ rotate: -10, opacity: 0 }}
                            transition={{ duration: 0.18 }}
                            className="text-2xl leading-none"
                        >
                            ×
                        </motion.span>
                    )}
                </AnimatePresence>
            </motion.button>

            {/* Chat window */}
            <AnimatePresence>
                {open && (
                    <motion.div
                        initial={{ opacity: 0, y: 16, scale: 0.98 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 18, scale: 0.98 }}
                        transition={{ type: "spring", stiffness: 380, damping: 28 }}
                        className="fixed bottom-24 right-6 w-[420px] max-w-[92vw] h-[640px] rounded-3xl overflow-hidden shadow-2xl border flex flex-col"
                        style={{ background: "var(--chat-panel)", borderColor: "var(--surface-border)", boxShadow: "var(--shadow-soft)" }}
                        dir={isRTL ? "rtl" : "ltr"}
                    >
                        {/* Header */}
                        <div className="p-4 border-b" style={{ background: "var(--chat-header-gradient)", borderColor: "transparent", color: "var(--text-white)" }}>
                            <div className="flex items-start justify-between gap-3">
                                <div className="flex items-center gap-3">
                                    <div className="h-10 w-10 rounded-2xl overflow-hidden border-2 shadow-md" style={{ borderColor: "var(--surface-border)" }}>
                                        <Image src={LeaAvatar} alt="LEA" className="h-full w-full object-cover" />
                                    </div>
                                    <div>
                                        <div className="font-bold leading-tight tracking-tight">
                                            Tire-Lait Express
                                        </div>
                                        <div className="flex items-center gap-2 text-xs mt-0.5" style={{ color: "rgba(255,255,255,.9)" }}>
                      <span className="relative flex h-2 w-2">
                        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                      </span>
                                            En ligne • Réponse en quelques secondes
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center gap-2">
                                    <div className="text-xs" style={{ color: "var(--text-white)" }}>
                                        <label className="mr-1" htmlFor="lang-select">{ui.lang}</label>
                                        <select
                                            id="lang-select"
                                            className="border rounded-full px-2 py-1 text-xs"
                                            style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                            value={language}
                                            onChange={(e) => applyLanguage(e.target.value)}
                                            title="Choisir la langue des réponses"
                                        >
                                            <option value="">—</option>
                                            <option value="fr">FR</option>
                                            <option value="en">EN</option>
                                            <option value="ar">AR</option>
                                        </select>
                                    </div>
                                    <button
                                        onClick={clearChat}
                                        className="text-xs px-3 py-1 rounded-full transition border"
                                        style={{ background: "var(--surface-strong)", borderColor: "var(--surface-border)", color: "var(--text-dark)" }}
                                        title={ui.reset}
                                    >
                                        {ui.reset}
                                    </button>
                                </div>
                            </div>
                        </div>

                        {/* Messages */}
                        <div className="flex-1 min-h-0 p-4 space-y-3 overflow-y-auto" style={{ background: "var(--chat-body-bg)" }}>
                            {messages.map((msg, i) => (
                                <motion.div
                                    key={i}
                                    initial={{ opacity: 0, y: 6 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    transition={{ duration: 0.18 }}
                                    className={`flex items-end ${
                                        msg.role === "user" ? "justify-end" : "justify-start"
                                    } gap-2`}
                                >
                                    {msg.role === "assistant" && (
                                        <div className="h-7 w-7 rounded-full overflow-hidden border shadow" style={{ borderColor: "var(--surface-border)" }}>
                                            <Image src={LeaAvatar} alt="LEA" className="h-full w-full object-cover" />
                                        </div>
                                    )}
                                    <div
                                        className={`max-w-[78%] rounded-3xl px-4 py-3 text-sm leading-relaxed whitespace-pre-line shadow-sm ${
                                            msg.role === "user" ? "text-white" : "border"
                                        }`}
                                        style={
                                            msg.role === "user"
                                                ? {
                                                    background: "var(--chat-user-bubble)",
                                                }
                                                : { background: "var(--chat-bot-bubble)", borderColor: "var(--chat-bot-border)", color: "var(--text-dark)" }
                                        }
                                    >
                                        {msg.content}
                                    </div>
                                </motion.div>
                            ))}

                            {loading && (
                                <motion.div
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    className="flex justify-start"
                                >
                                    <div className="rounded-3xl px-4 py-3 text-sm border" style={{ borderColor: "var(--surface-border)", background: "var(--surface)", color: "var(--text-muted)" }}>
                                        <TypingDots />
                                    </div>
                                </motion.div>
                            )}

                            <div ref={bottomRef} />
                        </div>

                        {/* Confirmation Summary Modal */}
                        <AnimatePresence>
                            {confirmOpen && (
                                <motion.div
                                    initial={{ opacity: 0, y: 10 }}
                                    animate={{ opacity: 1, y: 0 }}
                                    exit={{ opacity: 0, y: 10 }}
                                    transition={{ duration: 0.18 }}
                                    className="absolute inset-0 bg-black/20 flex items-end justify-center p-4"
                                    style={{ zIndex: 50 }}
                                >
                                    <div className="w-full rounded-2xl border shadow-xl p-4" style={{ background: "var(--surface)", borderColor: "var(--surface-border)" }}>
                                        <div className="font-semibold mb-2" style={{ color: "var(--text-dark)" }}>
                                            {language === "en" ? "Please confirm your order" : language === "ar" ? "يرجى تأكيد الطلب" : "Veuillez confirmer la commande"}
                                        </div>
                                        {confirmSummary && (
                                            <div className="text-sm space-y-2" style={{ color: "var(--text-dark)" }}>
                                                {!confirmEdit ? (
                                                    <>
                                                        {confirmSummary.name ? <div>• {language === "en" ? "Name" : language === "ar" ? "الاسم" : "Nom/Prénom"}: {confirmSummary.name}</div> : null}
                                                        {confirmSummary.start_date ? <div>• {language === "en" ? "Start date" : language === "ar" ? "تاريخ البدء" : "Date début"}: {confirmSummary.start_date}</div> : null}
                                                        {confirmSummary.end_date ? <div>• {language === "en" ? "End date" : language === "ar" ? "تاريخ النهاية" : "Date fin"}: {confirmSummary.end_date}</div> : null}
                                                        {confirmSummary.postal_code ? <div>• {language === "en" ? "Postal code" : language === "ar" ? "الرمز البريدي" : "Code postal"}: {confirmSummary.postal_code}</div> : null}
                                                        <div>• {language === "en" ? "Attachments" : language === "ar" ? "المرفقات" : "Pièces jointes"}: {filesCount}/2</div>
                                                    </>
                                                ) : (
                                                    <div className="grid grid-cols-2 gap-2">
                                                        <div className="col-span-2">
                                                            <label className="text-xs" style={{ color: "var(--text-muted)" }}>{language === "en" ? "Name" : language === "ar" ? "الاسم" : "Nom/Prénom"}</label>
                                                            <input className="w-full border rounded-xl px-3 py-2 text-sm" style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                                                value={editableSummary?.name || ""}
                                                                onChange={(e)=> setEditableSummary((s:any)=> ({...s, name: e.target.value}))}
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs" style={{ color: "var(--text-muted)" }}>{language === "en" ? "Start date" : language === "ar" ? "تاريخ البدء" : "Date début"}</label>
                                                            <input className="w-full border rounded-xl px-3 py-2 text-sm" style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                                                value={editableSummary?.start_date || ""}
                                                                onChange={(e)=> setEditableSummary((s:any)=> ({...s, start_date: e.target.value}))}
                                                                placeholder="22/01/2026"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs" style={{ color: "var(--text-muted)" }}>{language === "en" ? "End date" : language === "ar" ? "تاريخ النهاية" : "Date fin"}</label>
                                                            <input className="w-full border rounded-xl px-3 py-2 text-sm" style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                                                value={editableSummary?.end_date || ""}
                                                                onChange={(e)=> setEditableSummary((s:any)=> ({...s, end_date: e.target.value}))}
                                                                placeholder="29/01/2026"
                                                            />
                                                        </div>
                                                        <div>
                                                            <label className="text-xs" style={{ color: "var(--text-muted)" }}>{language === "en" ? "Postal code" : language === "ar" ? "الرمز البريدي" : "Code postal"}</label>
                                                            <input className="w-full border rounded-xl px-3 py-2 text-sm" style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                                                value={editableSummary?.postal_code || ""}
                                                                onChange={(e)=> setEditableSummary((s:any)=> ({...s, postal_code: e.target.value}))}
                                                                placeholder="69001"
                                                            />
                                                        </div>
                                                        <div className="col-span-2 text-[11px]" style={{ color: "var(--text-muted)" }}>
                                                            {language === "en" ? "Edit the fields then confirm." : language === "ar" ? "عدّل الحقول ثم أكد." : "Modifiez les champs puis confirmez."}
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                        <div className="mt-3 flex justify-end gap-2">
                                            <button onClick={cancelConfirm} className="px-3 py-1.5 rounded-full text-sm border" style={{ background: "var(--surface)", borderColor: "var(--surface-border)", color: "var(--text-dark)" }}>
                                                {confirmEdit ? (language === "en" ? "Done" : language === "ar" ? "تم" : "Terminer") : (language === "en" ? "Edit" : language === "ar" ? "تعديل" : "Modifier")}
                                            </button>
                                            <button onClick={confirmOrder} className="px-3 py-1.5 rounded-full text-sm text-white" style={{ background: "var(--chat-user-bubble)" }}>
                                                {language === "en" ? "Confirm" : language === "ar" ? "تأكيد" : "Confirmer"}
                                            </button>
                                        </div>
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>

                        {/* Quick actions */}
                        <div className="px-4 py-2 border-t flex gap-2 overflow-x-auto" style={{ background: "var(--surface)", borderColor: "var(--surface-border)", pointerEvents: confirmOpen ? "none" : "auto", opacity: confirmOpen ? 0.6 : 1 }}>
                            {/* Quick buttons */}
                            {ui.quick.map((label) => (
                                <button
                                    key={label}
                                    onClick={() => sendMessage(label)}
                                    className="px-3 py-1.5 rounded-full text-xs whitespace-nowrap"
                                    style={{ background: "var(--surface)", border: "1px solid var(--surface-border)", color: "var(--text-dark)" }}
                                >
                                    {label}
                                </button>
                            ))}
                            
                            {/* Intent buttons */}
                            {ui.intents?.map((intent) => (
                                <button
                                    key={intent}
                                    onClick={() => sendMessage(intent)}
                                    className="px-3 py-1.5 rounded-full text-xs whitespace-nowrap font-medium transition"
                                    style={{ color: "var(--text-dark)", background: "var(--surface)", border: "1px solid var(--surface-border)" }}
                                    title={`Send: ${intent}`}
                                >
                                    {intent}
                                </button>
                            ))}
                            
                            {/* Q/A button */}
                            <button
                                onClick={askFAQ}
                                disabled={loading}
                                className="px-3 py-1.5 rounded-full text-xs whitespace-nowrap disabled:opacity-60"
                                style={{ background: "var(--surface)", border: "1px solid var(--surface-border)", color: "var(--text-dark)" }}
                                title="Répondre via la base de questions"
                            >
                                {ui.qa}
                            </button>
                        </div>

                        {/* ✅ PJ uniquement si nécessaire */}
                        {attachmentsVisible && (
                            <div className="px-4 py-2 border-t" style={{ background: "var(--surface)", borderColor: "var(--surface-border)", pointerEvents: confirmOpen ? "none" : "auto", opacity: confirmOpen ? 0.6 : 1 }}>
                                <div className="flex items-center justify-between gap-2">
                                    <button
                                        type="button"
                                        onClick={() => { setAttachmentsOpen((v) => !v); setTimeout(focusComposer, 50); }}
                                        className="flex items-center gap-2 text-xs font-semibold"
                                        style={{ color: "var(--text-dark)" }}
                                        title="Afficher / masquer les pièces jointes"
                                    >
                                        <span className="select-none">📎 {ui.attachments}</span>
                                        <span className="text-[11px] font-normal" style={{ color: "var(--text-muted)" }}>
                      ({filesCount}/2)
                    </span>
                                        <span
                                            className={`ml-1 inline-block transition-transform ${
                                                attachmentsOpen ? "rotate-180" : "rotate-0"
                                            }`}
                                        >
                      ▾
                    </span>
                                    </button>

                                    <div className="relative">
                                        <button
                                            type="button"
                                            onClick={() => setShowAttachTip((v) => !v)}
                                            className="h-7 w-7 rounded-full text-xs flex items-center justify-center"
                                            style={{ background: "var(--surface)", border: "1px solid var(--surface-border)", color: "var(--text-dark)" }}
                                            title="Help"
                                        >
                                            i
                                        </button>

                                        <AnimatePresence>
                                            {showAttachTip && (
                                                <motion.div
                                                    initial={{ opacity: 0, y: 6, scale: 0.98 }}
                                                    animate={{ opacity: 1, y: 0, scale: 1 }}
                                                    exit={{ opacity: 0, y: 6, scale: 0.98 }}
                                                    transition={{ duration: 0.15 }}
                                                    className="absolute right-0 mt-2 w-[240px] rounded-2xl backdrop-blur shadow-xl p-3 text-[11px]"
                                                    style={{ border: "1px solid var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                                                >
                                                    {ui.tip}
                                                </motion.div>
                                            )}
                                        </AnimatePresence>
                                    </div>
                                </div>

                                <AnimatePresence initial={false}>
                                    {attachmentsOpen && (
                                        <motion.div
                                            initial={{ opacity: 0, height: 0 }}
                                            animate={{ opacity: 1, height: "auto" }}
                                            exit={{ opacity: 0, height: 0 }}
                                            transition={{ duration: 0.18 }}
                                            className="overflow-hidden"
                                        >
                                            <div className="mt-2 grid grid-cols-2 gap-2">
                                                <FileSlot
                                                    title={ui.prescription}
                                                    required
                                                    accept=".pdf,image/*"
                                                    file={prescriptionFile}
                                                    disabled={loading}
                                                    onChangeFile={setPrescriptionFile}
                                                    onClear={() => setPrescriptionFile(null)}
                                                    extraRight={
                                                        <button
                                                            type="button"
                                                            onClick={askFAQ}
                                                            disabled={loading}
                                                            className="text-[10px] px-2 py-1 rounded-full disabled:opacity-60"
                                                            style={{ background: "var(--surface)", border: "1px solid var(--surface-border)", color: "var(--text-dark)" }}
                                                            title="Répondre via la base de questions"
                                                        >
                                                            {ui.qa}
                                                        </button>
                                                    }
                                                    labels={{
                                                        required: ui.requiredDot,
                                                        none: ui.fileNone,
                                                        remove: ui.fileRemove,
                                                        add: ui.fileAdd,
                                                        replace: ui.fileReplace,
                                                        hint: ui.fileHint,
                                                    }}
                                                />
                                                <FileSlot
                                                    title={ui.insurance}
                                                    required
                                                    accept=".pdf,image/*"
                                                    file={insuranceFile}
                                                    disabled={loading}
                                                    onChangeFile={setInsuranceFile}
                                                    onClear={() => setInsuranceFile(null)}
                                                    labels={{
                                                        required: ui.requiredDot,
                                                        none: ui.fileNone,
                                                        remove: ui.fileRemove,
                                                        add: ui.fileAdd,
                                                        replace: ui.fileReplace,
                                                        hint: ui.fileHint,
                                                    }}
                                                />
                                            </div>
                                        </motion.div>
                                    )}
                                </AnimatePresence>
                            </div>
                        )}

                        {/* Input */}
                        <div className="p-3 border-t flex gap-2" style={{ background: "var(--surface)", borderColor: "var(--surface-border)", pointerEvents: confirmOpen ? "none" : "auto", opacity: confirmOpen ? 0.6 : 1 }}>
                            <div className="flex-1 relative">
                <textarea
                    ref={textareaRef}
                    className="w-full border rounded-2xl px-4 py-2.5 text-sm outline-none placeholder:text-gray-500 resize-none focus:ring-0"
                    style={{ borderColor: "var(--surface-border)", background: "var(--surface-strong)", color: "var(--text-dark)" }}
                    placeholder={ui.inputPlaceholder}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={onTextareaKeyDown}
                    disabled={loading}
                    rows={2}
                />
                            </div>

                            <motion.button
                                onClick={() => sendMessage()}
                                className="px-4 py-2.5 rounded-2xl text-sm text-white shadow-md disabled:opacity-60 self-end border"
                                style={{
                                    background: "var(--chat-user-bubble)",
                                    borderColor: "transparent",
                                    boxShadow: "var(--shadow-float)",
                                }}
                                whileHover={{ scale: 1.02 }}
                                whileTap={{ scale: 0.97 }}
                                disabled={loading}
                            >
                                {ui.send}
                            </motion.button>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </div>
    );
}