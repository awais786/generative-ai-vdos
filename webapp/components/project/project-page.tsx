'use client'

import { useCallback, useState } from 'react'
import dynamic from 'next/dynamic'
import { Project } from '@/lib/project-types'
import PlanningView from './planning-view'
import PlanEditor from './plan-editor'
import DoneView from './done-view'
import FailedView from './failed-view'
import ImageReviewView from './image-review-view'

// ssr: false — GeneratingView uses browser-only APIs (setTimeout, visibilityState)
const GeneratingView = dynamic(() => import('./generating-view'), { ssr: false })

interface Props {
  initialProject: Project
}

export default function ProjectPage({ initialProject }: Props) {
  const [project, setProject] = useState<Project>(initialProject)

  const updateProject = useCallback((updates: Partial<Project>) => {
    setProject(prev => ({ ...prev, ...updates }))
  }, [])

  const { status } = project

  if (status === 'DRAFT' || status === 'PLANNING') {
    return <PlanningView project={project} onUpdate={updateProject} />
  }
  if (status === 'REVIEW') {
    return <PlanEditor project={project} onUpdate={updateProject} />
  }
  if (status === 'GENERATING' || status === 'VIDEO_GENERATING') {
    return <GeneratingView project={project} onUpdate={updateProject} />
  }
  if (status === 'IMAGE_REVIEW') {
    return <ImageReviewView project={project} onUpdate={updateProject} />
  }
  if (status === 'DONE') {
    return <DoneView project={project} onUpdate={updateProject} />
  }
  return <FailedView project={project} onUpdate={updateProject} />
}
