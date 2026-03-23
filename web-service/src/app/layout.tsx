import type { Metadata } from "next";
import "./globals.css";
import { AuthWrapper } from "./auth-wrapper";

export const metadata: Metadata = {
  metadataBase: new URL("https://supacam.com"),
  title: {
    default: "SupaCam — AI Multi-Camera Auto Editing",
    template: "%s | SupaCam",
  },
  description:
    "Record with multiple phones, AI edits automatically. Free multi-camera cross-editing for vlog, interview, dance, and more.",
  keywords: [
    "SupaCam", "multi-camera", "multicam", "AI video editing", "auto editing",
    "cross-cut", "timeline cam", "vlog", "interview recording", "멀티캠", "AI 영상 편집",
  ],
  authors: [{ name: "SupaCam" }],
  creator: "SupaCam",
  robots: { index: true, follow: true },
  alternates: {
    canonical: "https://supacam.com",
  },
  openGraph: {
    title: "SupaCam — AI Multi-Camera Auto Editing",
    description: "Record with multiple phones, AI edits automatically. Free multi-camera cross-editing.",
    type: "website",
    locale: "en_US",
    alternateLocale: "ko_KR",
    siteName: "SupaCam",
    url: "https://supacam.com",
  },
  twitter: {
    card: "summary_large_image",
    title: "SupaCam — AI Multi-Camera Auto Editing",
    description: "Record with multiple phones, AI edits automatically.",
    creator: "@supacam",
  },
  icons: {
    icon: [
      { url: "/favicon.ico", sizes: "32x32" },
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
    ],
    apple: "/apple-touch-icon.png",
  },
  manifest: "/manifest.json",
};

const gaId = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID;

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <meta name="theme-color" content="#7c3aed" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="default" />
        <meta name="apple-mobile-web-app-title" content="SupaCam" />
        {/* JSON-LD Structured Data */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "SoftwareApplication",
              name: "SupaCam",
              applicationCategory: "MultimediaApplication",
              operatingSystem: "Web, iOS, Android",
              description: "AI-powered multi-camera auto editing. Record with multiple phones and let AI create professional cross-cut edits automatically.",
              url: "https://supacam.com",
              offers: [
                {
                  "@type": "Offer",
                  name: "Free",
                  price: "0",
                  priceCurrency: "USD",
                  description: "2 MultiCam sessions + 2 Timeline Cam sessions free",
                },
                {
                  "@type": "Offer",
                  name: "Plus",
                  price: "3",
                  priceCurrency: "USD",
                  description: "Unlimited sessions + AI Director mode + auto subtitles + BGM",
                  priceValidUntil: "2027-12-31",
                },
              ],
              aggregateRating: {
                "@type": "AggregateRating",
                ratingValue: "4.8",
                ratingCount: "12",
              },
            }),
          }}
        />
        {/* FAQ Structured Data for AEO */}
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: JSON.stringify({
              "@context": "https://schema.org",
              "@type": "FAQPage",
              mainEntity: [
                {
                  "@type": "Question",
                  name: "What is SupaCam?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "SupaCam is an AI-powered multi-camera editing tool. Record video from multiple phones simultaneously, and AI automatically creates professional cross-cut edits. No editing skills required.",
                  },
                },
                {
                  "@type": "Question",
                  name: "How does multi-camera recording work?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Open SupaCam on multiple phones, join the same session, and tap record. All cameras sync automatically. When done, AI analyzes all angles and creates a professionally edited video with smooth transitions.",
                  },
                },
                {
                  "@type": "Question",
                  name: "Is SupaCam free?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Yes! SupaCam offers 2 free MultiCam sessions and 2 free Timeline Cam sessions. For unlimited recording and premium features like AI Director mode and auto subtitles, upgrade to Plus for $3/month.",
                  },
                },
                {
                  "@type": "Question",
                  name: "What is Timeline Cam?",
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: "Timeline Cam lets you record, pause, and resume freely from one or more devices. All clips are automatically aligned on a single timeline, making it perfect for tutorials, cooking videos, and day-in-my-life vlogs.",
                  },
                },
              ],
            }),
          }}
        />
        {/* Paddle.js */}
        <script src="https://cdn.paddle.com/paddle/v2/paddle.js" async />
        {/* Google Analytics */}
        {gaId && (
          <>
            <script async src={`https://www.googletagmanager.com/gtag/js?id=${gaId}`} />
            <script
              dangerouslySetInnerHTML={{
                __html: `window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}gtag('js',new Date());gtag('config','${gaId}');`,
              }}
            />
          </>
        )}
      </head>
      <body className="antialiased">
        <AuthWrapper>{children}</AuthWrapper>
      </body>
    </html>
  );
}
