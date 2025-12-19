'use client';

import { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import 'katex/dist/katex.min.css';
import {
    Send, Sun, Moon, FileText, X, Scale,
    Paperclip, Loader2, Trash2, Gavel, Book,
    AlertTriangle, Copy, Check, Reply, ScrollText,
    RefreshCw, Briefcase, ShieldAlert, Coins
} from 'lucide-react';

interface Message {
    id: number;
    text: string;
    sender: 'user' | 'ai';
    attachment?: {
        type: 'image' | 'pdf';
        preview: string;
    };
    replyTo?: {
        id: number;
        text: string;
        sender: 'user' | 'ai';
    };
}

const SUGGESTION_POOL = [
    { icon: <ScrollText size={16}/>, text: 'Analisis kontrak kerja karyawan' },
    { icon: <Scale size={16}/>, text: 'Dasar hukum PHK efisiensi' },
    { icon: <Book size={16}/>, text: 'Syarat sah perjanjian KUHPerdata' },
    { icon: <ShieldAlert size={16}/>, text: 'Sanksi kebocoran data UU PDP' },
    { icon: <FileText size={16}/>, text: 'Prosedur RUPS Luar Biasa' },
    { icon: <AlertTriangle size={16}/>, text: 'Kebijakan gratifikasi perusahaan' },
    { icon: <Briefcase size={16}/>, text: 'Drafting Non-Disclosure Agreement' },
    { icon: <Coins size={16}/>, text: 'Aspek pajak akuisisi saham' },
    { icon: <Gavel size={16}/>, text: 'Penyelesaian sengketa arbitrase' },
    { icon: <Scale size={16}/>, text: 'Hak Kekayaan Intelektual software' },
    { icon: <Book size={16}/>, text: 'Legal Due Diligence merger' },
    { icon: <FileText size={16}/>, text: 'Struktur Joint Venture asing' }
];

export default function LawFellas() {
    const [input, setInput] = useState('');
    const [messages, setMessages] = useState<Message[]>([]);
    const [loading, setLoading] = useState(false);
    const [darkMode, setDarkMode] = useState(true);
    const [file, setFile] = useState<{ base64: string; mime: string; name: string } | null>(null);
    const [randomSuggestions, setRandomSuggestions] = useState<typeof SUGGESTION_POOL>([]);
    const [copiedId, setCopiedId] = useState<number | null>(null);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [replyingTo, setReplyingTo] = useState<Message | null>(null);

    const messagesEndRef = useRef<HTMLDivElement>(null);
    const fileInputRef = useRef<HTMLInputElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);

    useEffect(() => {
        messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }, [messages, loading, replyingTo]);

    useEffect(() => {
        if (darkMode) document.documentElement.classList.add('dark');
        else document.documentElement.classList.remove('dark');
    }, [darkMode]);

    useEffect(() => {
        const saved = localStorage.getItem('lawfellas_history_v2');
        if (saved) {
            try { setMessages(JSON.parse(saved)); } catch (e) { console.error(e); }
        }
        shuffleSuggestions();
    }, []);

    useEffect(() => {
        localStorage.setItem('lawfellas_history_v2', JSON.stringify(messages));
    }, [messages]);

    const shuffleSuggestions = () => {
        setIsRefreshing(true);
        setTimeout(() => {
            const shuffled = [...SUGGESTION_POOL].sort(() => 0.5 - Math.random());
            setRandomSuggestions(shuffled.slice(0, 4));
            setIsRefreshing(false);
        }, 300);
    };

    const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const selected = e.target.files?.[0];
        if (!selected) return;

        if (selected.size > 5 * 1024 * 1024) {
            alert("File terlalu besar (Maks 5MB)");
            return;
        }

        const reader = new FileReader();
        reader.onload = () => {
            const result = reader.result as string;
            const base64Data = result.split(',')[1];
            setFile({
                base64: base64Data,
                mime: selected.type,
                name: selected.name
            });
        };
        reader.readAsDataURL(selected);
        e.target.value = '';
    };

    const clearChat = () => {
        if (confirm("Hapus semua riwayat percakapan?")) {
            setMessages([]);
            localStorage.removeItem('lawfellas_history_v2');
        }
    };

    const handleCopy = (text: string, id: number) => {
        navigator.clipboard.writeText(text).then(() => {
            setCopiedId(id);
            setTimeout(() => setCopiedId(null), 2000);
        });
    };

    const handleReply = (message: Message) => {
        setReplyingTo(message);
        textareaRef.current?.focus();
    };

    const cancelReply = () => {
        setReplyingTo(null);
    };

    const scrollToMessage = (id: number) => {
        const element = document.getElementById(`msg-${id}`);
        if (element) {
            element.scrollIntoView({ behavior: 'smooth', block: 'center' });
            element.classList.add('ring-2', 'ring-red-500', 'ring-offset-2');
            setTimeout(() => element.classList.remove('ring-2', 'ring-red-500', 'ring-offset-2'), 1000);
        }
    };

    const sendMessage = async () => {
        if ((!input.trim() && !file) || loading) return;

        const currentFile = file;
        const currentInput = input;
        const currentReply = replyingTo;

        const newUserMessage: Message = {
            id: Date.now(),
            text: currentInput,
            sender: 'user',
            attachment: currentFile ? {
                type: currentFile.mime.includes('pdf') ? 'pdf' : 'image',
                preview: `data:${currentFile.mime};base64,${currentFile.base64}`
            } : undefined,
            replyTo: currentReply ? {
                id: currentReply.id,
                text: currentReply.text,
                sender: currentReply.sender
            } : undefined
        };

        setMessages(prev => [...prev, newUserMessage]);
        setInput('');
        setFile(null);
        setReplyingTo(null);
        setLoading(true);

        if (textareaRef.current) {
            textareaRef.current.style.height = '48px';
        }

        try {
            const fullHistory = [...messages, newUserMessage].map(msg => ({
                role: msg.sender === 'user' ? 'user' : 'model',
                parts: [{ text: msg.text }]
            }));

            const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8080'}/chat`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    history: fullHistory,
                    image: currentFile?.base64 || "",
                    mimeType: currentFile?.mime || ""
                }),
            });

            const data = await res.json();
            if (data.error) throw new Error(data.error);

            setMessages(prev => [...prev, {
                id: Date.now() + 1,
                text: data.response,
                sender: 'ai'
            }]);

        } catch (err) {
            setMessages(prev => [...prev, {
                id: Date.now() + 1,
                text: "⚠️ Gagal terhubung ke server. Pastikan backend berjalan.",
                sender: 'ai'
            }]);
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className={`flex flex-col h-[100dvh] font-sans antialiased transition-colors duration-300 ${darkMode ? 'bg-[#0a0a0a] text-gray-100' : 'bg-gray-50 text-gray-900'}`}>

            <header className={`sticky top-0 z-50 border-b backdrop-blur-md ${darkMode ? 'bg-[#0a0a0a]/80 border-gray-800' : 'bg-white/80 border-gray-200'}`}>
                <div className="w-full px-4 md:px-8 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className={`p-2 rounded-xl shadow-sm ${darkMode ? 'bg-gray-800 text-red-500' : 'bg-white text-red-600 border border-gray-100'}`}>
                            <Scale className="w-5 h-5" />
                        </div>
                        <div>
                            <h1 className="font-semibold text-base tracking-tight leading-tight">LawFellas</h1>
                            <p className={`text-[10px] uppercase tracking-wider font-medium ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>Corporate AI</p>
                        </div>
                    </div>

                    <div className="flex items-center gap-1">
                        <button
                            onClick={() => setDarkMode(!darkMode)}
                            className={`p-2 rounded-lg transition-all active:scale-95 ${darkMode ? 'hover:bg-gray-800 text-gray-400' : 'hover:bg-gray-100 text-gray-500'}`}
                        >
                            {darkMode ? <Sun size={18} /> : <Moon size={18} />}
                        </button>
                        <button
                            onClick={clearChat}
                            className={`p-2 rounded-lg transition-all active:scale-95 ${darkMode ? 'hover:bg-gray-800 text-gray-400' : 'hover:bg-gray-100 text-gray-500'}`}
                        >
                            <Trash2 size={18} />
                        </button>
                    </div>
                </div>
            </header>

            <main className="flex-1 overflow-y-auto w-full px-4 pb-4 scroll-smooth [&::-webkit-scrollbar]:hidden [-ms-overflow-style:'none'] [scrollbar-width:'none']">
                <div className="max-w-3xl mx-auto min-h-full flex flex-col">
                    {messages.length === 0 ? (
                        <div className="flex flex-col items-center justify-center flex-grow animate-in fade-in zoom-in duration-300 py-10">
                            <div className={`p-4 rounded-3xl mb-6 shadow-sm ${darkMode ? 'bg-gray-900 text-red-500' : 'bg-white text-red-600 border border-gray-100'}`}>
                                <Gavel className="w-10 h-10" />
                            </div>
                            <h2 className="text-xl md:text-2xl font-bold mb-2 text-center">Selamat Datang di LawFellas</h2>
                            <p className={`max-w-xs md:max-w-md text-center mb-8 text-sm md:text-base ${darkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                                Asisten hukum cerdas siap membantu analisis dokumen, regulasi, dan kontrak.
                            </p>

                            <div className="w-full max-w-xl">
                                <div className="flex justify-between items-center mb-3 px-1">
                                    <span className={`text-xs font-medium uppercase tracking-wider ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>Saran Pertanyaan</span>
                                    <button
                                        onClick={shuffleSuggestions}
                                        className={`p-1.5 rounded-full hover:bg-opacity-20 transition-all ${isRefreshing ? 'animate-spin' : ''} ${darkMode ? 'hover:bg-gray-700 text-gray-500' : 'hover:bg-gray-200 text-gray-400'}`}
                                        title="Ganti Pertanyaan"
                                    >
                                        <RefreshCw size={14} />
                                    </button>
                                </div>
                                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                                    {randomSuggestions.map((item, i) => (
                                        <button
                                            key={i}
                                            onClick={() => setInput(item.text)}
                                            className={`text-left px-4 py-3.5 rounded-xl text-xs md:text-sm transition-all hover:-translate-y-0.5 duration-200 ${
                                                darkMode
                                                    ? 'bg-gray-900 hover:bg-gray-800 border border-gray-800'
                                                    : 'bg-white hover:bg-white border border-gray-200 shadow-sm hover:shadow-md'
                                            }`}
                                        >
                                            <div className="flex items-center gap-3">
                                                <span className={`flex-shrink-0 ${darkMode ? 'text-gray-500' : 'text-red-500/70'}`}>{item.icon}</span>
                                                <span className="font-medium line-clamp-1">{item.text}</span>
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    ) : (
                        <div className="space-y-6 py-6">
                            {messages.map((msg) => (
                                <div id={`msg-${msg.id}`} key={msg.id} className={`flex flex-col group ${msg.sender === 'user' ? 'items-end' : 'items-start'} scroll-mt-24`}>
                                    <div className={`max-w-[90%] md:max-w-[85%] ${msg.sender === 'user' ? '' : ''}`}>
                                        {msg.sender === 'ai' && (
                                            <div className={`flex items-center mb-1.5 gap-2 px-1 ${darkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                                                <Scale className="w-3.5 h-3.5" />
                                                <span className="text-[10px] font-bold uppercase tracking-wider">LawFellas</span>
                                            </div>
                                        )}

                                        <div className={`px-5 py-3.5 rounded-2xl text-[13px] md:text-sm leading-relaxed shadow-sm overflow-hidden ${
                                            msg.sender === 'user'
                                                ? 'bg-red-600 text-white rounded-tr-sm'
                                                : (darkMode ? 'bg-gray-900 text-gray-200 border border-gray-800 rounded-tl-sm' : 'bg-white text-gray-800 border border-gray-100 rounded-tl-sm')
                                        }`}>
                                            {msg.replyTo && (
                                                <div
                                                    onClick={() => scrollToMessage(msg.replyTo!.id)}
                                                    className={`mb-3 p-2.5 rounded-lg border-l-[3px] cursor-pointer text-xs relative overflow-hidden ${
                                                        msg.sender === 'user'
                                                            ? 'bg-red-700/50 border-white/50 text-white/90'
                                                            : (darkMode ? 'bg-gray-800 border-red-500 text-gray-300' : 'bg-gray-100 border-red-500 text-gray-600')
                                                    }`}
                                                >
                                                    <p className={`font-bold text-[10px] mb-0.5 ${
                                                        msg.sender === 'user' ? 'text-white' : 'text-red-500'
                                                    }`}>
                                                        {msg.replyTo.sender === 'user' ? 'Anda' : 'LawFellas'}
                                                    </p>
                                                    <p className="line-clamp-1 opacity-80">{msg.replyTo.text}</p>
                                                </div>
                                            )}

                                            {msg.attachment && (
                                                <div className={`mb-3 p-2 rounded-lg inline-block overflow-hidden w-full ${
                                                    msg.sender === 'user'
                                                        ? 'bg-white/10 border-white/20 border'
                                                        : (darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-gray-100 border border-gray-200')
                                                }`}>
                                                    {msg.attachment.type === 'image' ? (
                                                        <img
                                                            src={msg.attachment.preview}
                                                            alt="Lampiran"
                                                            className="rounded-md max-h-48 w-full object-cover"
                                                        />
                                                    ) : (
                                                        <div className="flex items-center gap-2 px-2 py-1">
                                                            <FileText className={`w-4 h-4 ${msg.sender === 'user' ? 'text-white' : (darkMode ? 'text-red-400' : 'text-red-600')}`} />
                                                            <span className="text-xs font-medium">Dokumen PDF</span>
                                                        </div>
                                                    )}
                                                </div>
                                            )}

                                            <ReactMarkdown
                                                remarkPlugins={[remarkMath]}
                                                rehypePlugins={[rehypeKatex]}
                                                components={{
                                                    p: ({children}) => <p className="mb-2 last:mb-0">{children}</p>,
                                                    ul: ({children}) => <ul className="list-disc pl-4 space-y-1 my-2">{children}</ul>,
                                                    ol: ({children}) => <ol className="list-decimal pl-4 space-y-1 my-2">{children}</ol>,
                                                    a: ({children, href}) => (
                                                        <a href={href} className="underline decoration-white/30 hover:decoration-white" target="_blank" rel="noopener noreferrer">{children}</a>
                                                    ),
                                                    code: ({children}) => (
                                                        <code className={`px-1.5 py-0.5 rounded text-xs ${
                                                            msg.sender === 'user'
                                                                ? 'bg-white/20'
                                                                : (darkMode ? 'bg-gray-800' : 'bg-gray-100 text-red-700')
                                                        }`}>
                                                            {children}
                                                        </code>
                                                    )
                                                }}
                                            >
                                                {msg.text}
                                            </ReactMarkdown>
                                        </div>

                                        <div className={`flex gap-2 mt-1.5 px-1 transition-opacity duration-200 ${
                                            msg.sender === 'user' ? 'justify-end' : 'justify-start'
                                        }`}>
                                            <button
                                                onClick={() => handleCopy(msg.text, msg.id)}
                                                className={`text-[10px] flex items-center gap-1 px-2 py-1 rounded-full transition-colors ${
                                                    darkMode ? 'text-gray-500 hover:bg-gray-800 hover:text-gray-300' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'
                                                }`}
                                            >
                                                {copiedId === msg.id ? <Check size={12} className="text-green-500" /> : <Copy size={12} />}
                                                Salin
                                            </button>
                                            <button
                                                onClick={() => handleReply(msg)}
                                                className={`text-[10px] flex items-center gap-1 px-2 py-1 rounded-full transition-colors ${
                                                    darkMode ? 'text-gray-500 hover:bg-gray-800 hover:text-gray-300' : 'text-gray-400 hover:bg-gray-100 hover:text-gray-600'
                                                }`}
                                            >
                                                <Reply size={12} />
                                                Balas
                                            </button>
                                        </div>
                                    </div>
                                </div>
                            ))}
                            {loading && (
                                <div className="flex items-start gap-2">
                                    <div className={`p-2 rounded-full ${darkMode ? 'bg-gray-900' : 'bg-white'}`}>
                                        <Loader2 className="w-4 h-4 animate-spin text-red-600" />
                                    </div>
                                </div>
                            )}
                            <div ref={messagesEndRef} />
                        </div>
                    )}
                </div>
            </main>

            <footer className={`flex flex-col border-t ${darkMode ? 'bg-[#0a0a0a] border-gray-800' : 'bg-white border-gray-200'}`}>
                <div className="max-w-3xl mx-auto w-full">
                    {replyingTo && (
                        <div className={`px-4 pt-3 pb-1 flex items-center justify-between animate-in slide-in-from-bottom-2 ${
                            darkMode ? 'bg-[#0a0a0a]' : 'bg-white'
                        }`}>
                            <div className={`w-full flex-1 p-2 rounded-lg border-l-[3px] text-xs flex items-center justify-between gap-3 overflow-hidden ${
                                darkMode ? 'bg-gray-900 border-red-500 text-gray-300' : 'bg-gray-50 border-red-500 text-gray-700'
                            }`}>
                                <div className="flex-1 min-w-0">
                                    <p className="font-bold text-red-500 mb-0.5 text-[10px]">
                                        Balas ke {replyingTo.sender === 'user' ? 'Anda' : 'LawFellas'}
                                    </p>
                                    <p className="truncate opacity-80 block w-full">{replyingTo.text}</p>
                                </div>
                                <button onClick={cancelReply} className="flex-shrink-0 p-1.5 rounded-full hover:bg-black/10 dark:hover:bg-white/10">
                                    <X size={14} />
                                </button>
                            </div>
                        </div>
                    )}

                    {file && (
                        <div className={`px-4 pt-3 flex items-center justify-between text-xs animate-in slide-in-from-bottom-2`}>
                            <div className={`flex items-center gap-3 p-2.5 rounded-xl w-full ${
                                darkMode ? 'bg-gray-900 border border-gray-800' : 'bg-gray-50 border border-gray-200'
                            }`}>
                                <div className={`p-2 rounded-lg ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
                                    <FileText className={`w-4 h-4 ${file.mime.includes('pdf') ? 'text-red-500' : 'text-blue-500'}`} />
                                </div>
                                <div className="flex-1 min-w-0">
                                    <p className="font-medium truncate">{file.name}</p>
                                    <p className={`text-[10px] ${darkMode ? 'text-gray-500' : 'text-gray-400'}`}>Siap dikirim</p>
                                </div>
                                <button onClick={() => setFile(null)} className="p-1 rounded-full hover:bg-red-500/10 hover:text-red-500 transition-colors">
                                    <X size={16} />
                                </button>
                            </div>
                        </div>
                    )}

                    <div className="p-4 pt-2">
                        <div className={`flex gap-2 items-end p-1.5 rounded-[20px] border transition-all duration-200 focus-within:ring-2 focus-within:ring-red-500/20 ${
                            darkMode
                                ? 'bg-gray-900 border-gray-800 focus-within:border-red-500/50'
                                : 'bg-white border-gray-300 focus-within:border-red-500'
                        }`}>
                            <input
                                type="file"
                                ref={fileInputRef}
                                className="hidden"
                                accept="image/*,application/pdf"
                                onChange={handleFileSelect}
                            />
                            <button
                                onClick={() => fileInputRef.current?.click()}
                                className={`p-3 rounded-full flex-shrink-0 transition-colors ${
                                    darkMode
                                        ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
                                        : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
                                }`}
                            >
                                <Paperclip size={20} />
                            </button>

                            <textarea
                                ref={textareaRef}
                                rows={1}
                                value={input}
                                onChange={(e) => {
                                    setInput(e.target.value);
                                    e.target.style.height = 'auto';
                                    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
                                }}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter' && !e.shiftKey) {
                                        e.preventDefault();
                                        sendMessage();
                                    }
                                }}
                                placeholder={file ? "Tambahkan konteks..." : replyingTo ? "Ketik balasan..." : "Tanyakan sesuatu..."}
                                className={`flex-1 py-3 bg-transparent text-sm resize-none outline-none max-h-[120px] ${
                                    darkMode ? 'placeholder:text-gray-600' : 'placeholder:text-gray-400'
                                }`}
                                style={{ minHeight: '44px' }}
                            />

                            <button
                                onClick={sendMessage}
                                disabled={(!input.trim() && !file) || loading}
                                className={`p-3 rounded-[16px] flex-shrink-0 flex items-center justify-center transition-all ${
                                    (!input.trim() && !file) || loading
                                        ? (darkMode ? 'bg-gray-800 text-gray-600 cursor-not-allowed' : 'bg-gray-100 text-gray-300 cursor-not-allowed')
                                        : 'bg-red-600 hover:bg-red-700 text-white shadow-lg shadow-red-600/20 active:scale-95'
                                }`}
                            >
                                {loading ? <Loader2 size={20} className="animate-spin" /> : <Send size={20} className="ml-0.5" />}
                            </button>
                        </div>
                        <div className="text-center mt-2">
                            <p className={`text-[10px] ${darkMode ? 'text-gray-600' : 'text-gray-400'}`}>
                                AI dapat membuat kesalahan. Periksa kembali informasi penting.
                            </p>
                        </div>
                    </div>
                </div>
            </footer>
        </div>
    );
}