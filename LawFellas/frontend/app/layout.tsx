import type { Metadata, Viewport } from "next";
import "./globals.css";
// import { Providers } from "./providers"; // Uncomment jika Anda punya file providers

export const viewport: Viewport = {
    themeColor: "#0a0a0a", // Warna status bar (sesuai background LawFellas)
    width: "device-width",
    initialScale: 1,
    maximumScale: 1,
    userScalable: false, // PENTING: Mencegah zoom cubit, agar terasa seperti aplikasi native
};

export const metadata: Metadata = {
    title: "LawFellas",
    description: "Asisten hukum korporat cerdas",
    manifest: "/manifest.webmanifest", // Next.js App Router biasanya men-generate ekstensi .webmanifest dari manifest.ts
    icons: {
        icon: "/icon-192.png",
        apple: "/icon-192.png", // Icon untuk home screen iOS
    },
    appleWebApp: {
        capable: true, // Mengaktifkan mode standalone di iOS (hilangkan address bar Safari)
        statusBarStyle: "black-translucent", // Membuat status bar transparan/menyatu dengan header gelap
        title: "LawFellas",
    },
    formatDetection: {
        telephone: false, // Mencegah nomor telepon terdeteksi otomatis jadi link (opsional)
    },
};

export default function RootLayout({
                                       children,
                                   }: Readonly<{
    children: React.ReactNode;
}>) {
    return (
        <html lang="id">
        <body className="antialiased bg-[#0a0a0a]">
        {/* Jika nanti ada providers, bungkus children di sini */}
        {children}
        </body>
        </html>
    );
}