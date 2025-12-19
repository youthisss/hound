'use client';
/* eslintdisable */

import { useSession } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import Link from "next/link";
import Calendar from 'react-calendar';
import 'react-calendar/dist/Calendar.css';
import { format, isWithinInterval, startOfDay, endOfDay, parseISO } from 'date-fns';
import {
    ArrowLeft, History, ArrowDownCircle, ArrowUpCircle, RefreshCcw,
    Calendar as CalendarIcon, X
} from 'lucide-react';

interface Transaction {
    id: number;
    transaction_type: string;
    amount: number;
    weight_kg: number;
    waste_type?: { name: string };
    created_at: string;
    note: string;
}

export default function HistoryPage() {
    const { data: session, status } = useSession();
    const router = useRouter();
    const [allTransactions, setAllTransactions] = useState<Transaction[]>([]);
    const [filteredTransactions, setFilteredTransactions] = useState<Transaction[]>([]);
    const [loading, setLoading] = useState(true);
    const [dateRange, setDateRange] = useState<any>(null);
    const [showCalendar, setShowCalendar] = useState(false);


    useEffect(() => {
        if (status === "unauthenticated") {
            router.push("/login");
        }

        if (status === "authenticated" && session?.user?.accessToken) {
            fetchHistory(session.user.accessToken);
        }
    }, [status, session, router]);

    useEffect(() => {
        if (!allTransactions.length) return;

        if (Array.isArray(dateRange) && dateRange.length === 2 && dateRange[0] && dateRange[1]) {
            const startDate = startOfDay(dateRange[0]);
            const endDate = endOfDay(dateRange[1]);
            const filtered = allTransactions.filter((t) => {
                const trxDate = parseISO(t.created_at);
                return isWithinInterval(trxDate, { start: startDate, end: endDate });
            });
            setFilteredTransactions(filtered);
        } else if (dateRange instanceof Date) {
            const startDate = startOfDay(dateRange);
            const endDate = endOfDay(dateRange);
            const filtered = allTransactions.filter((t) => {
                const trxDate = parseISO(t.created_at);
                return isWithinInterval(trxDate, { start: startDate, end: endDate });
            });
            setFilteredTransactions(filtered);
        } else {
            setFilteredTransactions(allTransactions);
        }
    }, [dateRange, allTransactions]);

    const fetchHistory = async (token: string) => {
        setLoading(true);
        try {
            const res = await axios.get(`${process.env.NEXT_PUBLIC_API_URL}/my-history`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const data = res.data.riwayat || [];
            setAllTransactions(data);
            setFilteredTransactions(data);
        } catch (err) {
            console.error("Gagal ambil data:", err);
        } finally {
            setLoading(false);
        }
    };

    if (status === "loading") {
        return (
            <div className="flex h-screen w-full items-center justify-center bg-gray-50">
                <div className="h-12 w-12 animate-spin rounded-full border-4 border-emerald-600 border-t-transparent"></div>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-slate-50 font-sans text-slate-800">

            {/* --- HEADER --- */}
            <div className="bg-emerald-600 sticky top-0 z-30 shadow-lg">
                <div className="max-w-3xl mx-auto px-4 sm:px-6 lg:px-8 py-4">

                    <div className="flex justify-between items-center mb-4">
                        <div className="flex items-center gap-4">
                            <Link href="/dashboard" className="p-2 -ml-2 rounded-full hover:bg-emerald-700 text-white transition">
                                <ArrowLeft className="w-6 h-6" />
                            </Link>
                            <div>
                                <h1 className="text-xl font-bold text-white tracking-tight">Riwayat Transaksi</h1>
                                <p className="text-xs text-emerald-100 font-medium">Aktivitas tabungan Anda</p>
                            </div>
                        </div>
                        <button
                            onClick={() => session?.user?.accessToken && fetchHistory(session.user.accessToken)}
                            className="p-2 rounded-full hover:bg-emerald-700 text-white transition"
                            title="Refresh"
                        >
                            <RefreshCcw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
                        </button>
                    </div>

                    {/* --- FILTER DATE BAR --- */}
                    <div className="relative">
                        <button
                            onClick={() => setShowCalendar(!showCalendar)}
                            className="w-full flex items-center justify-between bg-white/10 text-white border border-white/20 rounded-xl px-4 py-2.5 text-sm font-medium hover:bg-white/20 transition backdrop-blur-sm"
                        >
              <span className="flex items-center gap-2">
                <CalendarIcon className="w-4 h-4" />
                  {Array.isArray(dateRange) && dateRange.length === 2 && dateRange[0] && dateRange[1]
                      ? `${format(dateRange[0], 'dd MMM yyyy')} - ${format(dateRange[1], 'dd MMM yyyy')}`
                      : dateRange instanceof Date
                          ? format(dateRange, 'dd MMM yyyy')
                          : 'Filter Tanggal'}
              </span>
                            {dateRange && (
                                <div
                                    onClick={(e) => { e.stopPropagation(); setDateRange(null); }}
                                    className="p-1 hover:bg-emerald-800 rounded-full"
                                >
                                    <X className="w-3 h-3" />
                                </div>
                            )}
                        </button>

                        {/* POPUP KALENDER */}
                        {showCalendar && (
                            <div className="absolute left-0 right-0 top-14 z-50 p-2">
                                <div className="bg-white rounded-2xl shadow-2xl border border-slate-100 p-2 animate-fade-in-up">
                                    <Calendar
                                        onChange={(value) => { setDateRange(value); setShowCalendar(false); }}
                                        value={dateRange}
                                        selectRange={true}
                                        className="border-none rounded-xl font-sans text-sm w-full"
                                    />
                                    <div className="flex justify-end p-2 border-t border-slate-50 mt-1">
                                        <button
                                            onClick={() => setShowCalendar(false)}
                                            className="text-xs font-bold text-emerald-600 hover:underline"
                                        >
                                            Tutup
                                        </button>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                </div>
            </div>

            {/* --- CONTENT --- */}
            <div className="max-w-3xl mx-auto p-4 sm:p-6 pb-20">

                {/* INFO FILTER */}
                {dateRange && (
                    <div className="mb-4 flex items-center justify-between text-xs text-slate-500 px-1">
                        <span>Menampilkan hasil filter:</span>
                        <span className="font-bold">{filteredTransactions.length} Transaksi ditemukan</span>
                    </div>
                )}

                {/* CARD LIST CONTAINER */}
                <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden min-h-[50vh]">
                    {loading ? (
                        <div className="p-10 flex flex-col items-center justify-center gap-4 text-slate-400 h-64">
                            <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-500 border-t-transparent"></div>
                            <p className="text-sm">Memuat data...</p>
                        </div>
                    ) : filteredTransactions.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-80 text-center p-8">
                            <div className="h-16 w-16 bg-slate-50 rounded-full flex items-center justify-center mb-4 text-slate-300">
                                <History className="w-8 h-8" />
                            </div>
                            <p className="text-slate-600 font-medium">Tidak ada transaksi ditemukan.</p>
                            <p className="text-xs text-slate-400 mt-1">
                                {dateRange ? "Coba ubah tanggal filter." : "Aktivitas tabungan Anda akan muncul di sini."}
                            </p>
                        </div>
                    ) : (
                        <div className="divide-y divide-slate-100">
                            {filteredTransactions.map((item) => (
                                <div key={item.id} className="p-5 flex justify-between items-center hover:bg-emerald-50/50 transition group cursor-default">
                                    <div className="flex items-center gap-4">
                                        {/* Icon Indikator */}
                                        <div className={`h-10 w-10 rounded-full flex items-center justify-center transition-transform group-hover:scale-105 shadow-sm ${
                                            item.transaction_type === 'DEPOSIT'
                                                ? 'bg-emerald-100 text-emerald-600'
                                                : 'bg-rose-100 text-rose-600'
                                        }`}>
                                            {item.transaction_type === 'DEPOSIT'
                                                ? <ArrowDownCircle className="w-5 h-5" />
                                                : <ArrowUpCircle className="w-5 h-5" />
                                            }
                                        </div>

                                        {/* Detail Teks */}
                                        <div>
                                            <p className="font-bold text-slate-800 text-sm">
                                                {item.transaction_type === 'DEPOSIT' ? 'Setor Sampah' : 'Penarikan Tunai'}
                                            </p>
                                            <div className="flex flex-col sm:flex-row sm:items-center sm:gap-2 text-xs text-slate-500 mt-0.5">
                                        <span className="font-medium">
                                            {new Date(item.created_at).toLocaleDateString('id-ID', {
                                                day: 'numeric', month: 'long', year: 'numeric'
                                            })}
                                        </span>
                                                <span className="hidden sm:inline text-slate-300">•</span>
                                                <span>
                                            {new Date(item.created_at).toLocaleTimeString('id-ID', {hour: '2-digit', minute:'2-digit'})}
                                        </span>
                                            </div>

                                            {/* Detail Sampah (Jika Deposit) */}
                                            {item.transaction_type === 'DEPOSIT' && item.waste_type && (
                                                <div className="mt-1.5 flex items-center gap-2">
                                            <span className="text-[10px] font-bold text-emerald-700 bg-emerald-50 border border-emerald-100 px-2 py-0.5 rounded-md uppercase tracking-wide">
                                                {item.waste_type.name}
                                            </span>
                                                    <span className="text-xs text-slate-500 font-medium">
                                                {item.weight_kg} kg
                                            </span>
                                                </div>
                                            )}

                                            {/* Catatan */}
                                            {item.note && <p className="text-xs text-slate-400 italic mt-1 line-clamp-1">"{item.note}"</p>}
                                        </div>
                                    </div>

                                    {/* Nominal Uang */}
                                    <div className={`text-sm sm:text-base font-bold whitespace-nowrap ${
                                        item.transaction_type === 'DEPOSIT' ? 'text-emerald-600' : 'text-rose-600'
                                    }`}>
                                        {item.transaction_type === 'DEPOSIT' ? '+' : '-'} Rp {item.amount.toLocaleString('id-ID')}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}