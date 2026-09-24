export const metadata = { title: "Agentic Edge — experiment monitor" };
import "./globals.css";
import Nav from "./components/Nav";
import { QueueProvider } from "./lib/queue-context";

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Inter:wght@400;500;600&display=swap" rel="stylesheet" />
      </head>
      <body>
        <QueueProvider>
          <div className="shell">
            <Nav />
            <div className="shell-main">{children}</div>
          </div>
        </QueueProvider>
      </body>
    </html>
  );
}
