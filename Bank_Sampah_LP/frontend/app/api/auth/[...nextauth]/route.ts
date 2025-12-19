/* eslintdisable */

import NextAuth from "next-auth";
import CredentialsProvider from "next-auth/providers/credentials";

const handler = NextAuth({
    providers: [
        CredentialsProvider({
            name: "Credentials",
            credentials: {
                username: { label: "Username", type: "text" },
                password: { label: "Password", type: "password" },
            },
            async authorize(credentials) {
                try {
                    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/login`, {
                        method: "POST",
                        body: JSON.stringify({
                            username: credentials?.username,
                            password: credentials?.password,
                        }),
                        headers: { "Content-Type": "application/json" },
                    });

                    const data = await res.json();

                    if (!res.ok) {
                        throw new Error(data.error || "Login gagal");
                    }

                    if (data.token) {
                        return {
                            id: data.user.id,
                            name: data.user.username,
                            username: data.user.username,
                            role: data.user.role,
                            token: data.token,
                        };
                    }
                    return null;
                } catch (error: any) {
                    throw new Error(error.message);
                }
            },
        }),
    ],
    callbacks: {
        async jwt({ token, user }: any) {
            if (user) {
                token.id = user.id;
                token.role = user.role;
                token.accessToken = user.token;
            }
            return token;
        },
        async session({ session, token }: any) {
            if (session.user) {
                session.user.id = token.id;
                session.user.role = token.role;
                session.user.username = session.user.name || "";
                session.user.accessToken = token.accessToken;
            }
            return session;
        },
    },
    pages: {
        signIn: "/login",
    },
});

export { handler as GET, handler as POST };