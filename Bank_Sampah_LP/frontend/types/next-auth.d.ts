import NextAuth from "next-auth";

declare module "next-auth" {
    interface Session {
        user: {
            id: number;
            name: string;
            username: string; // Kita tambah ini
            role: string;     // Kita tambah ini
            accessToken: string; // Kita tambah ini
        };
    }

    interface User {
        id: number;
        username: string;
        role: string;
        token: string;
    }
}

declare module "next-auth/jwt" {
    interface JWT {
        id: number;
        role: string;
        accessToken: string;
    }
}