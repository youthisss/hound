'use client';
/* eslintdisable */

import { useState } from 'react';
import { signIn } from 'next-auth/react';
import { useRouter } from 'next/navigation';
import { Shield, Lock, Loader2, ArrowRight, Eye, EyeOff, LayoutDashboard } from 'lucide-react';
import Link from 'next/link';

export default function AdminLoginPage() {
    const router = useRouter();
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setLoading(true);
        setError('');

        try {
            const result = await signIn('credentials', {
                username: username,
                password: password,
                redirect: false,
            });

            if (result?.error) {
                setError('Username atau Password salah!');
                setLoading(false);
                setPassword("");
            } else {
                router.push('/admin');
                router.refresh();
            }
        } catch (err) {
            setError('Terjadi kesalahan koneksi.');
            setLoading(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-slate-100 p-4 font-sans relative overflow-hidden">

            {/* Background Decoration (Blue Theme) */}
            <div className="absolute top-0 left-0 w-full h-full overflow-hidden pointer-events-none">
                <div className="absolute -top-24 -right-24 w-96 h-96 bg-blue-200 rounded-full mix-blend-multiply filter blur-3xl opacity-50 animate-blob"></div>
                <div className="absolute bottom-0 -left-20 w-72 h-72 bg-indigo-200 rounded-full mix-blend-multiply filter blur-3xl opacity-50 animate-blob animation-delay-2000"></div>
            </div>

            <div className="w-full max-w-md bg-white rounded-2xl shadow-xl border border-slate-200 relative z-10 overflow-hidden">

                {/* Header Admin - Nuansa Gelap/Profesional */}
                <div className="bg-slate-900 p-8 text-center relative">
                    <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 to-indigo-500"></div>

                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-xl bg-slate-800 text-blue-500 mb-4 shadow-lg border border-slate-700">
                        <Shield className="w-8 h-8" />
                    </div>
                    <h1 className="text-2xl font-bold text-white tracking-wide">Admin Portal</h1>
                    <p className="text-slate-400 text-sm mt-2">Akses khusus pengelola bank sampah</p>
                </div>

                {/* Form */}
                <div className="p-8">
                    {error && (
                        <div className="mb-6 bg-red-50 border-l-4 border-red-500 text-red-700 p-4 rounded-r-lg text-sm flex items-center animate-pulse">
                            <span className="mr-2">⚠️</span> {error}
                        </div>
                    )}

                    <form onSubmit={handleSubmit} className="space-y-5">

                        <div className="space-y-2">
                            <label className="text-sm font-bold text-slate-700 ml-1">Username Admin</label>
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400 group-focus-within:text-blue-600 transition-colors">
                                    <LayoutDashboard className="w-5 h-5" />
                                </div>
                                <input
                                    type="text"
                                    required
                                    placeholder="Masukan Username Anda"
                                    className="block w-full pl-12 pr-4 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-600 focus:border-transparent outline-none transition-all"
                                    value={username}
                                    onChange={(e) => setUsername(e.target.value)}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <label className="text-sm font-bold text-slate-700 ml-1">Password</label>
                            <div className="relative group">
                                <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none text-slate-400 group-focus-within:text-blue-600 transition-colors">
                                    <Lock className="w-5 h-5" />
                                </div>
                                <input
                                    type={showPassword ? "text" : "password"}
                                    required
                                    placeholder="••••••••"
                                    className="block w-full pl-12 pr-12 py-3 bg-slate-50 border border-slate-200 rounded-xl text-slate-800 focus:bg-white focus:ring-2 focus:ring-blue-600 focus:border-transparent outline-none transition-all"
                                    value={password}
                                    onChange={(e) => setPassword(e.target.value)}
                                />
                                <button
                                    type="button"
                                    onClick={() => setShowPassword(!showPassword)}
                                    className="absolute inset-y-0 right-0 pr-4 flex items-center text-slate-400 hover:text-blue-600 transition-colors focus:outline-none"
                                >
                                    {showPassword ? <EyeOff className="w-5 h-5" /> : <Eye className="w-5 h-5" />}
                                </button>
                            </div>
                        </div>

                        <button
                            type="submit"
                            disabled={loading}
                            className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 text-white font-bold py-3.5 rounded-xl shadow-lg shadow-blue-200 transform transition-all duration-200 active:scale-[0.98] disabled:opacity-70 disabled:cursor-not-allowed mt-6"
                        >
                            {loading ? (
                                <>
                                    <Loader2 className="w-5 h-5 animate-spin" />
                                    Memverifikasi...
                                </>
                            ) : (
                                <>
                                    Masuk Dashboard <ArrowRight className="w-5 h-5" />
                                </>
                            )}
                        </button>

                    </form>

                    {/* Link Kembali ke Login Nasabah */}
                    <div className="mt-8 text-center border-t border-slate-100 pt-6">
                        <Link href="/login" className="text-sm text-slate-500 hover:text-blue-600 font-medium transition-colors flex items-center justify-center gap-1">
                            &larr; Bukan Admin? Login Nasabah
                        </Link>
                    </div>
                </div>
            </div>
        </div>
    );
}