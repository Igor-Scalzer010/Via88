import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import "./globals.css";
export const metadata: Metadata = {
  title: "Via — Inteligência Rodoviária",
  description:
    "Um espaço para investigar a segurança das rodovias federais concedidas, com dados abertos da ANTT.",
};
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
