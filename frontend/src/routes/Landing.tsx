import AnnouncementBar from "../components/landing/AnnouncementBar";
import Hero from "../components/landing/Hero";
import FeatureStrip from "../components/landing/FeatureStrip";
import Footer from "../components/landing/Footer";

export default function Landing() {
  return (
    <div className="landing">
      <AnnouncementBar />
      <main>
        <Hero />
        <FeatureStrip />
      </main>
      <Footer />
    </div>
  );
}
