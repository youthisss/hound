'use client';
/* eslintdisable */

import { useState } from 'react';
import { signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { User, Lock, Loader2, Leaf, ArrowRight, Eye, EyeOff } from 'lucide-react';
import Link from 'next/link';

export default function LoginPage() {
    const router = useRouter();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false); // State untuk toggle password
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        const result = await signIn('credentials', {
            username: username,
            password: password,
            redirect: false,
        });

        if (result?.error) {
            setError('Username atau Password salah!');
            setLoading(false);
        } else {
            router.push('/dashboard');
            router.refresh();
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-emerald-50 to-teal-100 p-4 font-sans relative overflow-hidden">

            {/* Dekorasi Background */}
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
                <div className="absolute -top-24 -left-24 w-96 h-96 bg-emerald-200 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob"></div>
                <div className="absolute top-0 -right-4 w-72 h-72 bg-teal-200 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob animation-delay-2000"></div>
                <div className="absolute -bottom-8 left-20 w-72 h-72 bg-green-200 rounded-full mix-blend-multiply filter blur-3xl opacity-30 animate-blob animation-delay-4000"></div>
            </div>

            <div className="w-full max-w-md bg-white/80 backdrop-blur-xl rounded-3xl shadow-2xl overflow-hidden border border-white/50 relative z-10">

                {/* Header */}
                <div className="bg-emerald-600 p-8 text-center relative overflow-hidden">
                    <div className="absolute top-0 right-0 -mr-8 -mt-8 h-32 w-32 rounded-full bg-white/10 blur-xl"></div>
                    <div className="absolute bottom-0 left-0 -ml-8 -mb-8 h-24 w-24 rounded-full bg-white/10 blur-xl"></div>

                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-white text-emerald-600 mb-4 shadow-lg transform rotate-3 hover:rotate-6 transition-transform duration-300">
                        <Leaf className="w-8 h-8" />
                    </div>
                    <h1 className="text-2xl font-bold text-white tracking-normal">BANK SAMPAH LP</h1>
                    <p className="text-emerald-100 text-sm mt-1 font-medium">Masuk untuk mulai menabung</p>
                </div>

                {/* Form */}
                <div className="p-8 pt-10">
                    {error && (
                        <div className="mb-6 bg-red-50 border-l-4 border-red-500 text-red-700 p-4 rounded-r-lg text-sm flex items-center animate-pulse">
                            <span className="mr-2">⚠️</span> {error}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-6">

                        {/* Input Username */}
                        <div className="space-y-2">
                            <label className="text-sm font-semibold text-gray-600 ml-1">Username</label>
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-gray-400 group-focus-within:text-emerald-500 transition-colors">
                                    <User className="w-5 h-5" />
                                </div>
                                <input
                                    type="text"
                                    required
                                    placeholder="Masukkan Nomor Rumah Anda"
                                    className="block w-full pl-12 pr-4 py-3.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all duration-200"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                />
                            </div>
                        </div>

                        {/* Input Password */}
                        <div className="space-y-2">
                            <label className="text-sm font-semibold text-gray-600 ml-1">Password</label>
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-gray-400 group-focus-within:text-emerald-500 transition-colors">
                                    <Lock className="w-5 h-5" />
                                </div>
                                <input
                                    type={showPassword ? "text" : "password"} // Type dinamis
                                    required
                                    placeholder="••••••••"
                                    className="block w-full pl-12 pr-12 py-3.5 bg-gray-50 border border-gray-200 rounded-xl text-gray-700 focus:bg-white focus:ring-2 focus:ring-emerald-500 focus:border-emerald-500 outline-none transition-all duration-200"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                />
                                {/* Tombol Toggle Mata */}
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute inset-y-0 right-0 pr-4 flex items-center text-gray-400 hover:text-emerald-600 transition-colors focus:outline-none"
                                >
                                    {showPassword ? (
                                        <EyeOff className="w-5 h-5" />
                                    ) : (
                                        <Eye className="w-5 h-5" />
                                    )}
                                </button>
                            </div>
                        </div>

                        {/* Tombol Login */}
                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full flex items-center justify-center gap-2 bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-emerald-200 transform transition-all duration-200 active:scale-[0.98] disabled:opacity-70 disabled:cursor-not-allowed mt-8"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    Sedang Memproses...
                                </>
                            ) : (
                                <>
                                    Masuk Sekarang <ArrowRight className="w-5 h-5" />
                                </>
                            )}
                        </button>

                    </form>

                    {/* Footer Kecil */}
                    <div className="mt-8 text-center flex flex-col gap-2">
                        <p className="text-xs text-gray-400">
                            Lupa password? Hubungi <span className="text-emerald-600 font-semibold cursor-pointer hover:underline">Admin</span>
                        </p>
                        <Link href="/admin/login" className="text-xs text-emerald-600 font-semibold hover:underline mt-2 block">
                            Masuk sebagai Admin &rarr;
                        </Link>
                    </div>
                </div>
            </div>

            {/* Copyright Footer */}
            <div className="absolute bottom-6 text-center w-full text-emerald-800/40 text-xs font-medium">
                &copy; {new Date().getFullYear()} Bank Sampah Digital. All rights reserved.
            </div>

        </div>
    );
}