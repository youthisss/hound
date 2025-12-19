'use client';
/* eslintdisable */

import { useSession, signOut } from "next-auth/react";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import axios from "axios";
import Calendar from 'react-calendar';
import 'react-calendar/dist/Calendar.css';
import { isSameDay, parseISO } from 'date-fns';
import Link from "next/link";
import {
    RefreshCcw,
    LogOut,
    Wallet,
    Settings,
    Recycle,
    CalendarDays,
    ArrowDownCircle,
    ArrowUpCircle,
    Leaf,
    ChevronRight
} from 'lucide-react';


interface Transaction {
    id: number;
    transaction_type: string;
    amount: number;
    created_at: string;
    note: string;
}

interface WasteType {
    id: number;
    name: string;
    price: number;
    description: string;
}

interface DashboardData {
    saldo: number;
    riwayat: Transaction[];
}

export default function DashboardPage() {
    const { data: session, status } = useSession();
    const router = useRouter();

    const [data, setData] = useState<DashboardData | null>(null);
    const [wasteTypes, setWasteTypes] = useState<WasteType[]>([]);
    const [loading, setLoading] = useState(true);
    const [date, setDate] = useState<any>(new Date());
    const [greeting, setGreeting] = useState("Selamat Datang");

    useEffect(() => {
        if (status === "unauthenticated") {
            router.push("/login");
        }

        if (status === "authenticated" && session?.user?.accessToken) {
            fetchAllData(session.user.accessToken);
            determineGreeting();
        }
    }, [status, session, router]);

    const determineGreeting = () => {
        const hour = new Date().getHours();
        if (hour < 11) setGreeting("Selamat Pagi");
        else if (hour < 15) setGreeting("Selamat Siang");
        else if (hour < 18) setGreeting("Selamat Sore");
        else setGreeting("Selamat Malam");
    };

    const fetchAllData = async (token: string) => {
        setLoading(true);
        try {
            const [resHistory, resWaste] = await Promise.all([
                axios.get(`${process.env.NEXT_PUBLIC_API_URL}/my-history`, {
                    headers: { Authorization: `Bearer ${token}` },
                }),
                axios.get(`${process.env.NEXT_PUBLIC_API_URL}/waste-types`)
            ]);

            setData(resHistory.data);
            setWasteTypes(resWaste.data.data || []);
        } catch (err) {
            console.error("Gagal ambil data:", err);
        } finally {
            setLoading(false);
        }
    };

    const tileContent = ({ date, view }: any) => {
        if (view === 'month' && data?.riwayat) {
            const hasDeposit = data.riwayat.some(trx =>
                trx.transaction_type === 'DEPOSIT' && isSameDay(parseISO(trx.created_at), date)
            );
            const hasWithdraw = data.riwayat.some(trx =>
                trx.transaction_type === 'WITHDRAW' && isSameDay(parseISO(trx.created_at), date)
            );

            return (
                <div className="flex justify-center gap-1 mt-1">
                    {hasDeposit && <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 shadow-sm"></div>}
                    {hasWithdraw && <div className="h-1.5 w-1.5 rounded-full bg-rose-500 shadow-sm"></div>}
                </div>
            );
        }
        return null;
    };

    if (status === "loading") {
        return (
            <div className="flex h-screen w-full flex-col items-center justify-center bg-gray-50 gap-4">
                <div className="h-12 w-12 animate-spin rounded-full border-4 border-emerald-600 border-t-transparent"></div>
                <p className="text-gray-500 font-medium animate-pulse">Memuat data...</p>
            </div>
        );
    }

    return (
        <div className="min-h-screen bg-gray-50 pb-24 font-sans">

            {/* --- HEADER BACKGROUND (Gradient) --- */}
            <div className="relative bg-gradient-to-br from-emerald-800 to-green-600 pb-32 pt-8 text-white rounded-b-[3rem] shadow-2xl overflow-hidden">
                <div className="absolute top-0 right-0 -mr-16 -mt-16 h-64 w-64 rounded-full bg-white opacity-5 blur-3xl"></div>
                <div className="absolute bottom-0 left-0 -ml-16 -mb-16 h-40 w-40 rounded-full bg-white opacity-10 blur-2xl"></div>

                <div className="px-6 flex justify-between items-start relative z-10">
                    <div>
                        <p className="text-emerald-100 text-md font-semibold tracking-wide mb-1 opacity-90">{greeting},</p>
                        <div className="flex items-center gap-2">
                            <h1 className="text-4xl font-bold capitalize tracking-wide">{session?.user?.name}</h1>
                        </div>
                    </div>
                    <div className="flex gap-3">
                        <button
                            onClick={() => session?.user?.accessToken && fetchAllData(session.user.accessToken)}
                            className="rounded-full bg-white/20 p-2.5 backdrop-blur-sm hover:bg-white/30 transition shadow-inner"
                            title="Refresh Data"
                        >
                            <RefreshCcw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
                        </button>
                        <button
                            onClick={() => signOut({ callbackUrl: '/login' })}
                            className="rounded-full bg-white/20 p-2.5 backdrop-blur-sm hover:bg-rose-500/80 hover:text-white transition shadow-inner"
                            title="Keluar"
                        >
                            <LogOut className="w-5 h-5" />
                        </button>
                    </div>
                </div>
            </div>

            <div className="px-5 -mt-24 relative z-20 space-y-6">

                {/* --- FLOATING CARD (Saldo) --- */}
                <div className="bg-white rounded-3xl p-6 shadow-xl border border-gray-100">
                    <div className="flex justify-between items-start mb-2">
                        <div>
                            <p className="text-gray-500 text-xs font-semibold uppercase tracking-wider mb-1">Total Saldo Tabungan</p>
                            <div className="flex items-baseline gap-1 text-gray-800">
                                <span className="text-lg font-bold text-emerald-600">Rp</span>
                                <span className="text-4xl font-extrabold tracking-tight">
                  {data?.saldo?.toLocaleString('id-ID') || 0}
                </span>
                            </div>
                        </div>
                        <div className="h-10 w-10 bg-emerald-100 rounded-full flex items-center justify-center text-emerald-600">
                            <Wallet className="w-5 h-5" />
                        </div>
                    </div>
                    <div className="h-1 w-full bg-gray-100 rounded-full overflow-hidden">
                        <div className="h-full bg-emerald-500 w-2/3 rounded-full opacity-50"></div>
                    </div>
                    {/* Tombol Admin (Jika Admin) */}
                    {session?.user?.role === 'admin' && (
                        <div className="mt-4 pt-4 border-t border-gray-100">
                            <Link href="/admin" className="flex items-center justify-center gap-2 w-full bg-blue-50 text-blue-600 font-bold py-3 rounded-xl hover:bg-blue-100 transition shadow-sm">
                                <Settings className="w-5 h-5" />
                                <span>Input Transaksi Baru</span>
                            </Link>
                        </div>
                    )}
                </div>

                {/* --- HARGA SAMPAH (Horizontal Scroll) --- */}
                <div>
                    <div className="flex items-center justify-between mb-3 px-1">
                        <h2 className="text-gray-800 font-bold text-xl tracking-wide flex items-center gap-2">
                            <Recycle className="w-4 h-4 text-emerald-600" />
                            Harga Pasar
                        </h2>
                        <span className="text-md font-bold text-emerald-600 bg-emerald-200 px-2 py-1 rounded-md">Hari Ini</span>
                    </div>

                    <div className="flex overflow-x-auto gap-3 pb-4 scrollbar-hide -mx-1 px-1">
                        {wasteTypes.map((item, idx) => (
                            <div key={item.id} className={`min-w-[150px] p-4 rounded-2xl shadow-sm border border-gray-100 flex-shrink-0 flex flex-col justify-between ${
                                idx % 2 === 0 ? 'bg-white' : 'bg-emerald-50/50'
                            }`}>
                                <div className="flex justify-between items-start mb-2">
                                    <div className="h-8 w-8 rounded-full bg-gray-100 flex items-center justify-center text-emerald-600">
                                        <Recycle className="w-5 h-5" />
                                    </div>
                                </div>
                                <div>
                                    <p className="text-xs text-gray-500 font-bold uppercase truncate mb-1">{item.name}</p>
                                    <p className="text-lg font-bold text-gray-800">Rp {item.price.toLocaleString('id-ID')}</p>
                                    <p className="text-[10px] text-gray-400">per Kilogram</p>
                                </div>
                            </div>
                        ))}
                        {wasteTypes.length === 0 && (
                            <div className="w-full bg-white p-4 rounded-xl text-center text-sm text-gray-400 italic">
                                Data harga sedang dimuat...
                            </div>
                        )}
                    </div>
                </div>

                {/* --- GRID UTAMA (Kalender & History) --- */}
                <div className="grid gap-6">

                    {/* KALENDER */}
                    <div className="bg-white rounded-3xl shadow-sm p-5 border border-gray-100">
                        <h2 className="text-gray-800 font-bold text-lg mb-4 flex items-center gap-2">
                            <CalendarDays className="w-5 h-5 text-emerald-600" />
                            Aktivitas Menabung
                        </h2>
                        <div className="bg-gray-50/50 rounded-2xl p-2">
                            <Calendar
                                onChange={setDate}
                                value={date}
                                tileContent={tileContent}
                                locale="id-ID"
                                prev2Label={null}
                                next2Label={null}
                                className="!bg-transparent !border-none !w-full !font-sans"
                            />
                        </div>
                        <div className="flex justify-center gap-6 text-xs font-medium text-gray-500 pt-4">
                            <div className="flex items-center gap-2">
                                <span className="h-2 w-2 rounded-full bg-emerald-500"></span> Menabung
                            </div>
                            <div className="flex items-center gap-2">
                                <span className="h-2 w-2 rounded-full bg-rose-500"></span> Penarikan
                            </div>
                        </div>
                    </div>

                    {/* RIWAYAT TRANSAKSI */}
                    <div className="pb-10">
                        <h2 className="text-gray-800 font-bold text-lg mb-4 px-1 flex items-center justify-between">
                            <span>Riwayat Terakhir</span>
                            <Link href="/history" className="text-xs font-bold text-emerald-600 bg-emerald-200 px-3 py-1 rounded-full cursor-pointer hover:bg-emerald-100 flex items-center gap-1">
                                Lihat Semua <ChevronRight className="w-3 h-3" />
                            </Link>
                        </h2>
                        <div className="space-y-4">
                            {data?.riwayat?.slice(0, 5).map((item) => (
                                <div key={item.id} className="group bg-white p-4 rounded-2xl shadow-sm border border-gray-100 hover:shadow-md transition-all flex justify-between items-center">
                                    <div className="flex items-center gap-4">
                                        <div className={`h-12 w-12 rounded-2xl flex items-center justify-center transition-transform group-hover:scale-110 ${
                                            item.transaction_type === 'DEPOSIT'
                                                ? 'bg-emerald-100/80 text-emerald-600'
                                                : 'bg-rose-100/80 text-rose-600'
                                        }`}>
                                            {item.transaction_type === 'DEPOSIT' ? (
                                                <ArrowDownCircle className="w-6 h-6" />
                                            ) : (
                                                <ArrowUpCircle className="w-6 h-6" />
                                            )}
                                        </div>
                                        <div>
                                            <p className="font-bold text-gray-800">
                                                {item.transaction_type === 'DEPOSIT' ? 'Setor Sampah' : 'Tarik Tunai'}
                                            </p>
                                            <div className="flex items-center gap-2 text-xs text-gray-500 mt-1">
                                <span>
                                    {new Date(item.created_at).toLocaleDateString('id-ID', {
                                        day: 'numeric', month: 'short'
                                    })}
                                </span>
                                                <span className="h-1 w-1 bg-gray-300 rounded-full"></span>
                                                <span className="truncate max-w-[100px]">{item.note || '-'}</span>
                                            </div>
                                        </div>
                                    </div>
                                    <div className={`text-sm font-extrabold ${
                                        item.transaction_type === 'DEPOSIT' ? 'text-emerald-600' : 'text-gray-800'
                                    }`}>
                                        {item.transaction_type === 'DEPOSIT' ? '+' : '-'} Rp {item.amount.toLocaleString('id-ID')}
                                    </div>
                                </div>
                            ))}

                            {(!data?.riwayat || data.riwayat.length === 0) && (
                                <div className="flex flex-col items-center justify-center p-8 bg-white rounded-2xl border border-dashed border-gray-300 text-center">
                                    <div className="h-12 w-12 bg-gray-50 rounded-full flex items-center justify-center mb-3 text-emerald-600">
                                        <Leaf className="w-6 h-6" />
                                    </div>
                                    <p className="text-gray-500 font-medium">Belum ada aktivitas.</p>
                                    <p className="text-xs text-gray-400 mt-1">Yuk mulai setor sampahmu!</p>
                                </div>
                            )}
                        </div>
                    </div>

                </div>
            </div>
        </div>
    );
}