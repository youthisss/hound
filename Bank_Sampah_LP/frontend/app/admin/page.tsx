'use client';
/* eslintdisable */

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import Link from "next/link";
import Calendar from 'react-calendar';
import 'react-calendar/dist/Calendar.css';
import { format, isSameDay, parseISO } from 'date-fns';
import {
    ArrowLeft, Save, CheckCircle, AlertCircle, ClipboardList,
    Trash2, Edit, Plus, History, Coins, Lock, Search, Users, UserCog, Key, LayoutDashboard, X, Calendar as CalendarIcon, RefreshCcw, UserPlus
} from 'lucide-react';

interface WasteType {
    id: number;
    name: string;
    price: number;
    description: string;
}

interface Transaction {
    id: number;
    user: { full_name: string; username: string };
    transaction_type: string;
    amount: number;
    weight_kg: number;
    waste_type?: { id: number, name: string, price: number };
    created_at: string;
    note: string;
}

interface UserData {
    id: number;
    full_name: string;
    username: string;
    created_at: string;
    balance: number;
}

export default function AdminPage() {
    const { data: session, status } = useSession();
    const router = useRouter();
    const [activeTab, setActiveTab] = useState("input");
    const [wasteTypes, setWasteTypes] = useState<WasteType[]>([]);
    const [transactions, setTransactions] = useState<Transaction[]>([]);
    const [users, setUsers] = useState<UserData[]>([]);
    const [loadingData, setLoadingData] = useState(false);
    const [dateRange, setDateRange] = useState<any>(null);
    const [showCalendar, setShowCalendar] = useState(false);
    const [todaysCount, setTodaysCount] = useState(0);
    const [nasabahUsername, setNasabahUsername] = useState("");
    const [transactionType, setTransactionType] = useState("DEPOSIT");
    const [selectedWasteId, setSelectedWasteId] = useState<number | null>(null);
    const [weight, setWeight] = useState("");
    const [note, setNote] = useState("");
    const [msg, setMsg] = useState("");
    const [editingTrx, setEditingTrx] = useState<Transaction | null>(null);
    const [editTrxType, setEditTrxType] = useState("DEPOSIT");
    const [editWasteId, setEditWasteId] = useState<number | null>(null);
    const [editWeight, setEditWeight] = useState("");
    const [editNote, setEditNote] = useState("");
    const [editingWaste, setEditingWaste] = useState<WasteType | null>(null);
    const [newWasteName, setNewWasteName] = useState("");
    const [newWastePrice, setNewWastePrice] = useState("");
    const [newWasteDesc, setNewWasteDesc] = useState("");
    const [editingUser, setEditingUser] = useState<UserData | null>(null);
    const [editFullName, setEditFullName] = useState("");
    const [editUsername, setEditUsername] = useState("");
    const [editPassword, setEditPassword] = useState("");
    const [newUserName, setNewUserName] = useState("");
    const [newUserFullName, setNewUserFullName] = useState("");
    const [newUserPassword, setNewUserPassword] = useState("");
    const [newUserMsg, setNewUserMsg] = useState("");
    const [loadingNewUser, setLoadingNewUser] = useState(false);

    useEffect(() => {
        if (status === "unauthenticated") router.push("/login");
        if (status === "authenticated" && session?.user?.role !== "admin") {
            router.replace("/dashboard");
        }
        if (session?.user?.accessToken) {
            fetchWasteTypes();
            if (activeTab === "history") fetchHistory();
            if (activeTab === "users") fetchUsers();
            else fetchHistory();
        }
    }, [status, session, activeTab, router]);

    useEffect(() => {
        if (activeTab === "history" && session?.user?.accessToken) {
            fetchHistory();
        }
    }, [dateRange]);

    const fetchWasteTypes = async () => {
        try {
            const res = await axios.get(`${process.env.NEXT_PUBLIC_API_URL}/waste-types?t=${new Date().getTime()}`);
            const rawData = res.data.data || [];
            setWasteTypes(rawData.sort((a: WasteType, b: WasteType) => b.id - a.id));
        } catch (err) { console.error(err); }
    };

    const fetchHistory = async () => {
        setLoadingData(true);
        try {
            let url = `${process.env.NEXT_PUBLIC_API_URL}/transactions/all`;
            if (Array.isArray(dateRange) && dateRange.length === 2 && dateRange[0] && dateRange[1]) {
                const startDate = format(dateRange[0], 'yyyy-MM-dd');
                const endDate = format(dateRange[1], 'yyyy-MM-dd');
                url += `?start_date=${startDate}&end_date=${endDate}`;
            } else if (dateRange instanceof Date) {
                const singleDate = format(dateRange, 'yyyy-MM-dd');
                url += `?start_date=${singleDate}&end_date=${singleDate}`;
            }

            const res = await axios.get(url, {
                headers: { Authorization: `Bearer ${session?.user?.accessToken}` },
            });

            const allData = res.data.data || [];
            setTransactions(allData);

            if(!dateRange) {
                const today = new Date();
                const count = allData.filter((t: Transaction) => isSameDay(parseISO(t.created_at), today)).length;
                setTodaysCount(count);
            }
        } catch (err) { console.error(err); }
        finally { setLoadingData(false); }
    };

    const fetchUsers = async () => {
        setLoadingData(true);
        try {
            const res = await axios.get(`${process.env.NEXT_PUBLIC_API_URL}/nasabah`, {
                headers: { Authorization: `Bearer ${session?.user?.accessToken}` },
            });
            setUsers(res.data.data || []);
        } catch (err) { console.error(err); }
        finally { setLoadingData(false); }
    };

    const handleTransaction = async (e: React.FormEvent) => {
        e.preventDefault();
        setMsg("");
        try {
            await axios.post(`${process.env.NEXT_PUBLIC_API_URL}/transactions`, {
                nasabah_username: nasabahUsername,
                transaction_type: transactionType,
                waste_type_id: transactionType === 'DEPOSIT' ? Number(selectedWasteId) : null,
                weight_kg: transactionType === 'DEPOSIT' ? Number(weight) : 0,
                amount_withdraw: transactionType === 'WITHDRAW' ? Number(weight) : 0,
                note: note,
            }, { headers: { Authorization: `Bearer ${session?.user?.accessToken}` } });

            setMsg("✅ Transaksi Berhasil Disimpan!");
            setNasabahUsername(""); setWeight(""); setNote("");
            fetchHistory();
        } catch (err: any) { setMsg("❌ Gagal: " + (err.response?.data?.error || "Error")); }
    };

    const prepareEditTrx = (trx: Transaction) => {
        setEditingTrx(trx);
        setEditTrxType(trx.transaction_type);
        setEditWasteId(trx.waste_type?.id || (wasteTypes.length > 0 ? wasteTypes[0].id : null));
        setEditWeight(trx.transaction_type === 'DEPOSIT' ? String(trx.weight_kg) : String(trx.amount));
        setEditNote(trx.note);
    };

    const handleUpdateTransaction = async (e: React.FormEvent) => {
        e.preventDefault();
        if(!editingTrx) return;
        try {
            const payload = {
                nasabah_username: editingTrx.user.username,
                transaction_type: editTrxType,
                waste_type_id: editTrxType === 'DEPOSIT' ? Number(editWasteId) : null,
                weight_kg: editTrxType === 'DEPOSIT' ? Number(editWeight) : 0,
                amount_withdraw: editTrxType === 'WITHDRAW' ? Number(editWeight) : 0,
                note: editNote
            };
            await axios.put(`${process.env.NEXT_PUBLIC_API_URL}/transactions/${editingTrx.id}`, payload, {
                headers: { Authorization: `Bearer ${session?.user?.accessToken}` }
            });
            alert("Transaksi berhasil diperbarui!");
            setEditingTrx(null);
            fetchHistory();
        } catch (err: any) { alert("Gagal update: " + (err.response?.data?.error || "Error")); }
    };

    const handleDeleteTransaction = async (id: number) => {
        if(!confirm("Hapus transaksi ini? Saldo nasabah akan berubah.")) return;
        try {
            await axios.delete(`${process.env.NEXT_PUBLIC_API_URL}/transactions/${id}`, {
                headers: { Authorization: `Bearer ${session?.user?.accessToken}` }
            });
            fetchHistory();
        } catch (err: any) { alert("Gagal hapus"); }
    };

    const handleSaveWaste = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!session?.user?.accessToken) return;
        try {
            const payload = { name: newWasteName, price: Number(newWastePrice), description: newWasteDesc };
            const headers = { Authorization: `Bearer ${session.user.accessToken}` };

            if (editingWaste) await axios.put(`${process.env.NEXT_PUBLIC_API_URL}/waste-types/${editingWaste.id}`, payload, { headers });
            else await axios.post(`${process.env.NEXT_PUBLIC_API_URL}/waste-types`, payload, { headers });

            await fetchWasteTypes();
            setEditingWaste(null); setNewWasteName(""); setNewWastePrice(""); setNewWasteDesc("");
            alert("Data sampah tersimpan!");
        } catch (err) { alert("Gagal menyimpan data."); }
    };

    const handleDeleteWaste = async (id: number) => {
        if(!confirm("Hapus jenis sampah ini?")) return;
        try {
            await axios.delete(`${process.env.NEXT_PUBLIC_API_URL}/waste-types/${id}`, {
                headers: { Authorization: `Bearer ${session?.user?.accessToken}` }
            });
            fetchWasteTypes();
        } catch (err) { alert("Gagal hapus"); }
    };

    const handleCreateNewUser = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoadingNewUser(true);
        setNewUserMsg("");

        if (!session?.user?.accessToken) return;

        try {
            await axios.post(`${process.env.NEXT_PUBLIC_API_URL}/nasabah`, {
                full_name: newUserFullName,
                username: newUserName,
                password: newUserPassword,
            }, { headers: { Authorization: `Bearer ${session.user.accessToken}` } });

            setNewUserMsg("✅ Nasabah berhasil didaftarkan!");
            setNewUserName("");
            setNewUserFullName("");
            setNewUserPassword("");
            fetchUsers();
        } catch (err: any) {
            setNewUserMsg("❌ Gagal: " + (err.response?.data?.error || "Terjadi kesalahan"));
        } finally {
            setLoadingNewUser(false);
        }
    };

    const handleEditUser = (user: UserData) => {
        setEditingUser(user);
        setEditFullName(user.full_name);
        setEditUsername(user.username);
        setEditPassword("");
    };

    const handleUpdateUser = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!editingUser || !session?.user?.accessToken) return;
        try {
            await axios.put(`${process.env.NEXT_PUBLIC_API_URL}/nasabah/${editingUser.id}`, {
                full_name: editFullName,
                username: editUsername,
                password: editPassword
            }, { headers: { Authorization: `Bearer ${session.user.accessToken}` } });
            alert("Data Nasabah Berhasil Diupdate!");
            setEditingUser(null);
            fetchUsers();
        } catch (err: any) { alert("Gagal update: " + (err.response?.data?.error || "Error")); }
    };

    if (status === "loading") return <div className="min-h-screen flex items-center justify-center bg-slate-50"><div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div></div>;
    if (!session || session.user.role !== "admin") return <div className="p-10 text-red-500 text-center"><Lock className="inline" /> Akses Ditolak</div>;

    return (
        <div className="min-h-screen bg-slate-50 font-sans text-slate-800">

            {/* NAVBAR */}
            <div className="bg-white border-b border-slate-200 sticky top-0 z-30 px-4 sm:px-6 lg:px-8 py-4 shadow-sm transition-all">
                <div className="max-w-7xl mx-auto flex justify-between items-center">
                    <div className="flex items-center gap-3">
                        <div className="bg-blue-600 p-2 rounded-lg text-white shadow-blue-200 shadow-lg">
                            <LayoutDashboard className="w-6 h-6" />
                        </div>
                        <div>
                            <h1 className="text-xl font-bold text-slate-800 leading-tight hidden sm:block">Admin Portal</h1>
                            <p className="text-xs text-slate-500 font-medium">Bank Sampah Digital</p>
                        </div>
                    </div>
                    <Link href="/dashboard" className="group flex items-center gap-2 text-sm font-medium text-slate-500 hover:text-blue-600 transition-colors bg-slate-100 hover:bg-blue-50 px-4 py-2 rounded-full">
                        <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
                        <span className="hidden sm:inline">Ke Dashboard Nasabah</span>
                        <span className="sm:hidden">Kembali</span>
                    </Link>
                </div>
            </div>

            <div className="max-w-7xl mx-auto p-4 sm:p-6 lg:p-8">

                {/* TABS */}
                <div className="flex flex-wrap justify-center md:justify-start gap-3 mb-8 bg-white p-1.5 rounded-2xl shadow-sm border border-slate-100 w-full md:w-fit mx-auto md:mx-0 overflow-x-auto">
                    {[
                        { id: "input", label: "Input Transaksi", icon: ClipboardList },
                        { id: "history", label: "Riwayat Global", icon: History },
                        { id: "users", label: "Kelola Nasabah", icon: Users },
                        { id: "waste", label: "Kelola Harga", icon: Coins },
                    ].map((tab) => (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`flex items-center gap-2 px-4 sm:px-6 py-2.5 rounded-xl text-sm font-semibold transition-all duration-200 whitespace-nowrap ${
                                activeTab === tab.id
                                    ? "bg-blue-600 text-white shadow-md shadow-blue-200 scale-105"
                                    : "text-slate-500 hover:bg-slate-50 hover:text-blue-600"
                            }`}
                        >
                            <tab.icon className="w-4 h-4" /> {tab.label}
                        </button>
                    ))}
                </div>

                {/* === CONTENT AREA === */}
                <div className="animate-fade-in-up">

                    {/* TAB 1: INPUT */}
                    {activeTab === "input" && (
                        <div className="grid lg:grid-cols-3 gap-6 lg:gap-8">
                            {/* Form Card */}
                            <div className="lg:col-span-2 bg-white rounded-3xl shadow-xl shadow-slate-200/50 overflow-hidden border border-slate-100">
                                <div className="bg-gradient-to-r from-blue-600 to-indigo-600 p-6 sm:p-8 text-white">
                                    <h2 className="text-xl font-bold flex items-center gap-2">
                                        <Plus className="w-6 h-6" /> Catat Transaksi Baru
                                    </h2>
                                    <p className="text-blue-100 text-sm mt-1 opacity-90">Masukkan data setoran atau penarikan nasabah.</p>
                                </div>

                                <div className="p-6 sm:p-8">
                                    {msg && (
                                        <div className={`mb-6 p-4 rounded-xl flex items-start gap-3 text-sm font-medium ${msg.includes("✅") ? "bg-emerald-50 text-emerald-700 border border-emerald-100" : "bg-rose-50 text-rose-700 border border-rose-100"}`}>
                                            {msg.includes("✅") ? <CheckCircle className="w-5 h-5 shrink-0"/> : <AlertCircle className="w-5 h-5 shrink-0"/>}
                                            {msg}
                                        </div>
                                    )}

                                    <form onSubmit={handleTransaction} className="space-y-6">
                                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                            <div className="space-y-2">
                                                <label className="text-sm font-bold text-slate-700">Username Nasabah</label>
                                                <div className="relative">
                                                    <Search className="absolute left-3 top-3 w-4 h-4 text-slate-400" />
                                                    <input type="text" required value={nasabahUsername} onChange={e => setNasabahUsername(e.target.value)}
                                                           className="w-full pl-10 pr-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none transition-all"
                                                           placeholder="Cari username..." />
                                                </div>
                                            </div>
                                            <div className="space-y-2">
                                                <label className="text-sm font-bold text-slate-700">Jenis Transaksi</label>
                                                <select value={transactionType} onChange={e => setTransactionType(e.target.value)}
                                                        className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none cursor-pointer">
                                                    <option value="DEPOSIT">🟢 Menabung (Deposit)</option>
                                                    <option value="WITHDRAW">🔴 Tarik Tunai (Withdraw)</option>
                                                </select>
                                            </div>
                                        </div>

                                        {transactionType === "DEPOSIT" ? (
                                            <div className="p-5 bg-emerald-50/50 rounded-2xl border border-emerald-100/50 space-y-4">
                                                <div className="space-y-2">
                                                    <label className="text-sm font-bold text-emerald-800">Jenis Sampah</label>
                                                    <select required onChange={e => setSelectedWasteId(Number(e.target.value))}
                                                            className="w-full px-4 py-2.5 bg-white border border-emerald-200 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none">
                                                        <option value="">-- Pilih Sampah --</option>
                                                        {wasteTypes.map(w => <option key={w.id} value={w.id}>{w.name} — Rp {w.price.toLocaleString('id-ID')}/kg</option>)}
                                                    </select>
                                                </div>
                                                <div className="space-y-2">
                                                    <label className="text-sm font-bold text-emerald-800">Berat (Kg)</label>
                                                    <input type="number" step="0.1" required value={weight} onChange={e => setWeight(e.target.value)}
                                                           className="w-full px-4 py-2.5 bg-white border border-emerald-200 rounded-xl focus:ring-2 focus:ring-emerald-500 outline-none" placeholder="Contoh: 2.5" />
                                                </div>
                                            </div>
                                        ) : (
                                            <div className="p-5 bg-rose-50/50 rounded-2xl border border-rose-100/50 space-y-4">
                                                <div className="space-y-2">
                                                    <label className="text-sm font-bold text-rose-800">Nominal Penarikan (Rp)</label>
                                                    <input type="number" required value={weight} onChange={e => setWeight(e.target.value)}
                                                           className="w-full px-4 py-2.5 bg-white border border-rose-200 rounded-xl focus:ring-2 focus:ring-rose-500 outline-none font-mono" placeholder="50000" />
                                                </div>
                                            </div>
                                        )}

                                        <div className="space-y-2">
                                            <label className="text-sm font-bold text-slate-700">Catatan <span className="font-normal text-slate-400">(Opsional)</span></label>
                                            <textarea rows={2} value={note} onChange={e => setNote(e.target.value)}
                                                      className="w-full px-4 py-2.5 bg-slate-50 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none resize-none" placeholder="Tambahkan catatan kecil..." />
                                        </div>

                                        <button type="submit" className="w-full py-3.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-bold shadow-lg shadow-blue-200 active:scale-[0.98] transition-all flex justify-center items-center gap-2">
                                            <Save className="w-5 h-5" /> PROSES TRANSAKSI
                                        </button>
                                    </form>
                                </div>
                            </div>

                            {/* Quick Stats / Info Side */}
                            <div className="space-y-6">
                                <div className="bg-white p-6 sm:p-8 rounded-3xl shadow-sm border border-slate-100">
                                    <h3 className="font-bold text-slate-800 mb-4">Statistik Singkat</h3>
                                    <div className="space-y-4">
                                        <div className="p-4 rounded-2xl bg-blue-50 text-blue-700">
                                            <p className="text-xs font-bold uppercase tracking-wider opacity-70">Total Jenis Sampah</p>
                                            <p className="text-3xl font-extrabold mt-1">{wasteTypes.length}</p>
                                        </div>
                                        <div className="p-4 rounded-2xl bg-indigo-50 text-indigo-700">
                                            <p className="text-xs font-bold uppercase tracking-wider opacity-70">Transaksi Hari Ini</p>
                                            <p className="text-3xl font-extrabold mt-1">{todaysCount}</p>
                                        </div>
                                    </div>
                                </div>
                                <div className="bg-gradient-to-br from-slate-800 to-slate-900 p-6 sm:p-8 rounded-3xl text-slate-300 shadow-lg">
                                    <h4 className="text-white font-bold mb-2">Tips Admin</h4>
                                    <p className="text-sm leading-relaxed">
                                        Pastikan username nasabah sudah benar sebelum menyimpan. Transaksi yang sudah disimpan tidak dapat diedit, hanya bisa dihapus lewat database langsung.
                                    </p>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* TAB 2: RIWAYAT (DENGAN FILTER KALENDER) */}
                    {activeTab === "history" && (
                        <div className="bg-white rounded-3xl shadow-xl shadow-slate-200/50 border border-slate-100 overflow-hidden flex flex-col h-[calc(100vh-240px)] min-h-[500px] relative">

                            {/* Toolbar Filter */}
                            <div className="p-4 sm:p-6 border-b border-slate-100 bg-slate-50/50 flex flex-wrap justify-between items-center sticky top-0 z-20 backdrop-blur-sm gap-4">
                                <div>
                                    <h2 className="font-bold text-lg text-slate-800">Database Transaksi</h2>
                                    <p className="text-sm text-slate-500">
                                        {Array.isArray(dateRange) && dateRange.length === 2 && dateRange[0] && dateRange[1]
                                            ? `${format(dateRange[0], 'dd MMM yyyy')} - ${format(dateRange[1], 'dd MMM yyyy')}`
                                            : 'Menampilkan semua transaksi'}
                                    </p>
                                </div>
                                <div className="flex items-center gap-2">
                                    <div className="relative">
                                        <button onClick={() => setShowCalendar(!showCalendar)} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-bold border transition ${showCalendar ? 'bg-blue-50 border-blue-200 text-blue-600' : 'bg-white border-slate-200 text-slate-600 hover:bg-slate-50'}`}>
                                            <CalendarIcon className="w-4 h-4" /> <span className="hidden sm:inline">Filter Tanggal</span>
                                        </button>
                                        {/* Popup Kalender (DENGAN CLASS KHUSUS ADMIN) */}
                                        {showCalendar && (
                                            <div className="absolute right-0 top-12 z-50 bg-white p-2 rounded-2xl shadow-2xl border border-slate-200 animate-fade-in-up admin-calendar-wrapper">
                                                <Calendar
                                                    onChange={(value) => { setDateRange(value); setShowCalendar(false); }}
                                                    value={dateRange}
                                                    selectRange={true}
                                                    className="border-none rounded-xl font-sans text-sm"
                                                />
                                                <div className="flex justify-between p-2 border-t border-slate-100 mt-2">
                                                    <button onClick={() => { setDateRange(null); setShowCalendar(false); }} className="text-xs font-bold text-slate-500 hover:text-red-500">Reset</button>
                                                    <button onClick={() => setShowCalendar(false)} className="text-xs font-bold text-blue-600 hover:underline">Tutup</button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                    <button onClick={fetchHistory} className="p-2 hover:bg-blue-50 rounded-xl transition-colors border border-slate-200 bg-white" title="Refresh">
                                        <RefreshCcw className="w-5 h-5 text-slate-500" />
                                    </button>
                                </div>
                            </div>

                            {/* Tabel */}
                            <div className="overflow-auto flex-1 p-0">
                                <table className="w-full text-sm text-left">
                                    <thead className="bg-slate-50 text-slate-500 font-semibold sticky top-0 z-10 shadow-sm">
                                    <tr>
                                        <th className="px-4 sm:px-6 py-4">Waktu</th>
                                        <th className="px-4 sm:px-6 py-4">Nasabah</th>
                                        <th className="px-4 sm:px-6 py-4">Jenis</th>
                                        <th className="px-4 sm:px-6 py-4">Detail Sampah</th>
                                        <th className="px-4 sm:px-6 py-4 text-right">Nominal</th>
                                        <th className="px-4 sm:px-6 py-4 text-right">Aksi</th>
                                    </tr>
                                    </thead>
                                    <tbody className="divide-y divide-slate-100">
                                    {loadingData ? <tr><td colSpan={6} className="p-10 text-center">Loading...</td></tr> :
                                        transactions.length === 0 ? <tr><td colSpan={6} className="p-10 text-center text-slate-400">Belum ada data transaksi.</td></tr> :
                                            transactions.map(trx => (
                                                <tr key={trx.id} className="hover:bg-blue-50/30 transition-colors group">
                                                    <td className="px-4 sm:px-6 py-4 whitespace-nowrap text-slate-500">
                                                        <div className="font-medium text-slate-700">{new Date(trx.created_at).toLocaleDateString('id-ID')}</div>
                                                        <div className="text-xs">{new Date(trx.created_at).toLocaleTimeString('id-ID', {hour: '2-digit', minute:'2-digit'})}</div>
                                                    </td>
                                                    <td className="px-4 sm:px-6 py-4">
                                                        <div className="font-bold text-slate-700">{trx.user?.full_name}</div>
                                                        <div className="text-xs text-slate-400 group-hover:text-blue-500 transition-colors">@{trx.user?.username}</div>
                                                    </td>
                                                    <td className="px-4 sm:px-6 py-4">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-bold border ${trx.transaction_type === 'DEPOSIT' ? 'bg-emerald-50 text-emerald-700 border-emerald-100' : 'bg-rose-50 text-rose-700 border-rose-100'}`}>
                            {trx.transaction_type === 'DEPOSIT' ? 'SETOR' : 'TARIK'}
                          </span>
                                                    </td>
                                                    <td className="px-4 sm:px-6 py-4 text-slate-600">
                                                        {trx.transaction_type === 'DEPOSIT' ? (
                                                            <div className="flex items-center gap-2">
                                                                <span className="font-medium">{trx.waste_type?.name || 'Sampah Terhapus'}</span>
                                                                <span className="text-slate-400">•</span>
                                                                <span className="bg-slate-100 px-2 py-0.5 rounded text-xs font-mono">{trx.weight_kg} kg</span>
                                                            </div>
                                                        ) : <span className="italic text-slate-400">Penarikan Tunai</span>}
                                                        {trx.note && <div className="text-xs text-slate-400 mt-1 italic">"{trx.note}"</div>}
                                                    </td>
                                                    <td className={`px-4 sm:px-6 py-4 text-right font-bold text-base ${trx.transaction_type === 'DEPOSIT' ? 'text-emerald-600' : 'text-rose-600'}`}>
                                                        {trx.transaction_type === 'DEPOSIT' ? '+' : '-'} {trx.amount.toLocaleString('id-ID')}
                                                    </td>
                                                    <td className="px-4 sm:px-6 py-4 text-right">
                                                        <div className="flex justify-end gap-2">
                                                            <button onClick={() => prepareEditTrx(trx)} className="p-2 bg-blue-50 text-blue-600 rounded-lg hover:bg-blue-100 transition" title="Edit"><Edit className="w-4 h-4" /></button>
                                                            <button onClick={() => handleDeleteTransaction(trx.id)} className="p-2 bg-rose-50 text-rose-600 rounded-lg hover:bg-rose-100 transition" title="Hapus"><Trash2 className="w-4 h-4" /></button>
                                                        </div>
                                                    </td>
                                                </tr>
                                            ))}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    )}

                    {/* TAB 3: USERS */}
                    {activeTab === "users" && (
                        <div className="grid lg:grid-cols-3 gap-6 lg:gap-8 items-start">

                            {/* Form Tambah Nasabah Baru (EKSPLISIT) */}
                            <div className="lg:col-span-1 bg-white p-6 sm:p-8 rounded-3xl shadow-lg border border-slate-100 sticky top-24">
                                <div className="mb-6 pb-4 border-b border-slate-100">
                                    <h3 className="font-bold text-slate-800 text-lg flex gap-2 items-center">
                                        <UserPlus className="w-5 h-5 text-blue-500"/> Daftar Nasabah Baru
                                    </h3>
                                    <p className="text-xs text-slate-500 mt-1">Berikan username dan password awal.</p>
                                </div>

                                {newUserMsg && (
                                    <div className={`mb-4 p-3 rounded-xl text-sm ${newUserMsg.includes("✅") ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"}`}>
                                        {newUserMsg}
                                    </div>
                                )}

                                <form onSubmit={handleCreateNewUser} className="space-y-4">
                                    <div className="space-y-1">
                                        <label className="text-xs font-bold text-slate-500 uppercase">Nama Lengkap</label>
                                        <input type="text" required placeholder="Nama Lengkap" className="w-full px-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm" value={newUserFullName} onChange={e => setNewUserFullName(e.target.value)} />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-xs font-bold text-slate-500 uppercase">Username</label>
                                        <input type="text" required placeholder="Username (cth: budi123)" className="w-full px-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm" value={newUserName} onChange={e => setNewUserName(e.target.value)} />
                                    </div>
                                    <div className="space-y-1">
                                        <label className="text-xs font-bold text-slate-500 uppercase">Password Awal</label>
                                        <input type="text" required placeholder="Min 4 karakter" className="w-full px-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm" value={newUserPassword} onChange={e => setNewUserPassword(e.target.value)} />
                                    </div>

                                    <div className="flex gap-2 pt-4">
                                        <button type="submit" disabled={loadingNewUser} className="flex-1 bg-blue-600 text-white py-2.5 rounded-xl hover:bg-blue-700 font-bold transition shadow-md shadow-blue-200 text-sm disabled:bg-slate-400">
                                            {loadingNewUser ? 'Mendaftarkan...' : 'Daftarkan Nasabah'}
                                        </button>
                                    </div>
                                </form>
                            </div>

                            {/* List Nasabah dengan Kolom SALDO */}
                            <div className="lg:col-span-2 bg-white rounded-3xl shadow-xl shadow-slate-200/50 border border-slate-100 overflow-hidden flex flex-col h-[calc(100vh-240px)] min-h-[500px] relative">
                                <div className="p-4 sm:p-6 border-b border-slate-100 bg-slate-50/50 flex justify-between items-center sticky top-0 z-20 backdrop-blur-sm">
                                    <div><h2 className="font-bold text-lg text-slate-800">Daftar Nasabah Terdaftar</h2><p className="text-sm text-slate-500">Total: {users.length} Akun</p></div>
                                    <button onClick={fetchUsers} className="text-sm text-blue-600 hover:underline">Refresh List</button>
                                </div>
                                <div className="overflow-auto flex-1 p-0">
                                    <table className="w-full text-sm text-left">
                                        <thead className="bg-slate-50 text-slate-500 font-semibold sticky top-0 z-10 shadow-sm">
                                        <tr>
                                            <th className="px-4 sm:px-6 py-4">Nama Lengkap</th>
                                            <th className="px-4 sm:px-6 py-4">Username</th>
                                            <th className="px-4 sm:px-6 py-4">Bergabung</th>
                                            <th className="px-4 sm:px-6 py-4 text-right">Saldo Saat Ini</th>
                                            <th className="px-4 sm:px-6 py-4 text-right">Aksi</th>
                                        </tr>
                                        </thead>
                                        <tbody className="divide-y divide-slate-100">
                                        {loadingData ? <tr><td colSpan={5} className="p-10 text-center">Loading...</td></tr> : users.map(u => (
                                            <tr key={u.id} className="hover:bg-slate-50">
                                                <td className="px-4 sm:px-6 py-4 font-bold text-slate-700">{u.full_name}</td>
                                                <td className="px-4 sm:px-6 py-4 text-slate-600">@{u.username}</td>
                                                <td className="px-4 sm:px-6 py-4 text-slate-500">{new Date(u.created_at).toLocaleDateString('id-ID')}</td>
                                                <td className="px-4 sm:px-6 py-4 text-right font-bold text-emerald-600">
                                                    Rp {(u.balance || 0).toLocaleString('id-ID')}
                                                </td>
                                                <td className="px-4 sm:px-6 py-4 text-right">
                                                    <button onClick={() => handleEditUser(u)} className="bg-blue-50 text-blue-600 px-3 py-1.5 rounded-lg text-xs font-bold hover:bg-blue-100 transition flex items-center gap-1 ml-auto">
                                                        <UserCog className="w-3 h-3" /> Edit
                                                    </button>
                                                </td>
                                            </tr>
                                        ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>

                        </div>
                    )}

                    {/* TAB 4: HARGA */}
                    {activeTab === "waste" && (
                        <div className="grid lg:grid-cols-3 gap-6 lg:gap-8 items-start">
                            <div className="lg:col-span-1 bg-white p-6 sm:p-8 rounded-3xl shadow-lg border border-slate-100 sticky top-24">
                                <div className="mb-6 pb-4 border-b border-slate-100"><h3 className="font-bold text-slate-800 text-lg flex gap-2 items-center">{editingWaste ? <Edit className="w-5 h-5 text-amber-500"/> : <Plus className="w-5 h-5 text-blue-500"/>} {editingWaste ? "Edit Harga Sampah" : "Tambah Jenis Baru"}</h3><p className="text-xs text-slate-500 mt-1">Atur nama dan harga beli per kilogram.</p></div>
                                <form onSubmit={handleSaveWaste} className="space-y-4">
                                    <div className="space-y-1"><label className="text-xs font-bold text-slate-500 uppercase">Nama Sampah</label><input type="text" required placeholder="Contoh: Tembaga" className="w-full px-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm" value={newWasteName} onChange={e => setNewWasteName(e.target.value)} /></div>
                                    <div className="space-y-1"><label className="text-xs font-bold text-slate-500 uppercase">Harga per KG</label><div className="relative"><span className="absolute left-4 top-2 text-slate-400 text-sm font-bold">Rp</span><input type="number" required placeholder="0" className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm font-mono" value={newWastePrice} onChange={e => setNewWastePrice(e.target.value)} /></div></div>
                                    <div className="space-y-1"><label className="text-xs font-bold text-slate-500 uppercase">Deskripsi</label><input type="text" placeholder="Keterangan singkat..." className="w-full px-4 py-2 border border-slate-200 rounded-xl focus:ring-2 focus:ring-blue-500 outline-none text-sm" value={newWasteDesc} onChange={e => setNewWasteDesc(e.target.value)} /></div>
                                    <div className="flex gap-2 pt-4"><button type="submit" className="flex-1 bg-blue-600 text-white py-2.5 rounded-xl hover:bg-blue-700 font-bold transition shadow-md shadow-blue-200 text-sm">{editingWaste ? "Update Harga" : "Simpan Baru"}</button>{editingWaste && (<button type="button" onClick={() => { setEditingWaste(null); setNewWasteName(""); setNewWastePrice(""); setNewWasteDesc(""); }} className="px-4 bg-slate-100 text-slate-600 rounded-xl hover:bg-slate-200 font-bold text-sm transition">Batal</button>)}</div>
                                </form>
                            </div>
                            <div className="lg:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-4 sm:gap-6">
                                {wasteTypes.map(w => (
                                    <div key={w.id} className="group bg-white p-6 rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:border-blue-200 transition-all duration-300 relative overflow-hidden">
                                        <div className="absolute top-0 right-0 w-24 h-24 bg-blue-50 rounded-bl-full -mr-4 -mt-4 opacity-50 group-hover:bg-blue-100 transition-colors"></div>
                                        <div className="relative z-10">
                                            <div className="flex justify-between items-start mb-2"><h4 className="font-bold text-lg text-slate-800">{w.name}</h4><div className="bg-emerald-50 text-emerald-700 px-2 py-1 rounded-lg text-xs font-bold font-mono">Rp {w.price.toLocaleString('id-ID')}</div></div>
                                            <p className="text-slate-500 text-sm mb-4 line-clamp-2 h-10">{w.description || "Tidak ada deskripsi"}</p>
                                            <div className="flex gap-2 pt-2 border-t border-slate-50"><button onClick={() => { setEditingWaste(w); setNewWasteName(w.name); setNewWastePrice(String(w.price)); setNewWasteDesc(w.description); }} className="flex-1 py-1.5 rounded-lg bg-slate-50 text-slate-600 text-xs font-bold hover:bg-blue-50 hover:text-blue-600 transition flex items-center justify-center gap-1"><Edit className="w-3 h-3" /> Edit</button><button onClick={() => handleDeleteWaste(w.id)} className="flex-1 py-1.5 rounded-lg bg-slate-50 text-slate-600 text-xs font-bold hover:bg-rose-50 hover:text-rose-600 transition flex items-center justify-center gap-1"><Trash2 className="w-3 h-3" /> Hapus</button></div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}

                </div>
            </div>

            {/* MODAL EDIT USER */}
            {editingUser && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-fade-in-up">
                        <div className="bg-blue-600 p-4 text-white flex justify-between items-center"><h3 className="font-bold flex items-center gap-2"><UserCog className="w-5 h-5"/> Edit Nasabah</h3><button onClick={() => setEditingUser(null)} className="hover:bg-blue-700 p-1 rounded-full text-white/80 hover:text-white"><X className="w-5 h-5"/></button></div>
                        <div className="p-6"><form onSubmit={handleUpdateUser} className="space-y-4"><div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Nama Lengkap</label><input type="text" required className="w-full p-2 border rounded-xl" value={editFullName} onChange={e => setEditFullName(e.target.value)} /></div><div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Username</label><input type="text" required className="w-full p-2 border rounded-xl bg-slate-50" value={editUsername} onChange={e => setEditUsername(e.target.value)} /></div><div className="pt-2"><label className="text-xs font-bold text-slate-500 uppercase flex items-center gap-1 mb-1"><Key className="w-3 h-3"/> Reset Password (Opsional)</label><input type="text" className="w-full p-2 border border-orange-200 bg-orange-50 rounded-xl text-orange-800 placeholder:text-orange-300" placeholder="Isi untuk ganti password baru" value={editPassword} onChange={e => setEditPassword(e.target.value)} /></div><button type="submit" className="w-full bg-blue-600 text-white py-3 rounded-xl font-bold hover:bg-blue-700 transition mt-4">Simpan Perubahan</button></form></div>
                    </div>
                </div>
            )}

            {/* MODAL EDIT TRANSAKSI */}
            {editingTrx && (
                <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4 backdrop-blur-sm">
                    <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md overflow-hidden animate-fade-in-up">
                        <div className="bg-indigo-600 p-4 text-white flex justify-between items-center"><h3 className="font-bold flex items-center gap-2"><Edit className="w-5 h-5"/> Edit Transaksi</h3><button onClick={() => setEditingTrx(null)} className="hover:bg-indigo-700 p-1 rounded-full text-white/80 hover:text-white"><X className="w-5 h-5"/></button></div>
                        <div className="p-6">
                            <form onSubmit={handleUpdateTransaction} className="space-y-4">
                                <div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Nasabah</label><input type="text" disabled className="w-full p-2 border rounded-xl bg-slate-100 text-slate-500 cursor-not-allowed" value={editingTrx.user.full_name} /></div>
                                <div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Jenis Transaksi</label><select value={editTrxType} onChange={e => setEditTrxType(e.target.value)} className="w-full p-2 border rounded-xl"><option value="DEPOSIT">Menabung</option><option value="WITHDRAW">Tarik Tunai</option></select></div>
                                {editTrxType === 'DEPOSIT' && (<div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Jenis Sampah</label><select value={Number(editWasteId)} onChange={e => setEditWasteId(Number(e.target.value))} className="w-full p-2 border rounded-xl">{wasteTypes.map(w => <option key={w.id} value={w.id}>{w.name} (Rp {w.price})</option>)}</select></div>)}
                                <div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">{editTrxType === 'DEPOSIT' ? 'Berat (Kg)' : 'Nominal (Rp)'}</label><input type="number" required className="w-full p-2 border rounded-xl" value={editWeight} onChange={e => setEditWeight(e.target.value)} /></div>
                                <div><label className="text-xs font-bold text-slate-500 uppercase block mb-1">Catatan</label><input type="text" className="w-full p-2 border rounded-xl" value={editNote} onChange={e => setEditNote(e.target.value)} /></div>
                                <button type="submit" className="w-full bg-indigo-600 text-white py-3 rounded-xl font-bold hover:bg-indigo-700 transition mt-4">Simpan Perubahan</button>
                            </form>
                        </div>
                    </div>
                </div>
            )}

        </div>
    );
}