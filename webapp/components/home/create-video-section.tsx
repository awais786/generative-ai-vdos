import ProjectForm from './project-form'

export default function CreateVideoSection() {
  return (
    <section>
      <h2 className="text-lg font-semibold text-[#e7e9ee] mb-1">Create a video</h2>
      <p className="text-sm text-[#9aa3b2] mb-4">
        Describe an idea. We&apos;ll write a shot plan you can review and refine before anything is generated.
      </p>
      <ProjectForm />
    </section>
  )
}
