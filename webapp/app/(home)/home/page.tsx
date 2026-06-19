import { Suspense } from 'react'
import ProjectsSection from "@/components/home/project-section";
import CreateVideoSection from "@/components/home/create-video-section";
import WelcomeBanner from "@/components/home/welcome";
import WelcomeSkeleton from "@/components/home/welcome-skeleton";

export default function HomePage() {
  return (
    <div className="space-y-7">
      <Suspense fallback={<WelcomeSkeleton />}>
        <WelcomeBanner />
      </Suspense>

      <CreateVideoSection />

      <ProjectsSection />
    </div>
  )
}
