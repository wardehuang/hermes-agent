'use client'

import { type FC, useEffect, useState } from 'react'

import { useI18n } from '@/i18n'
import { generatedVideoFromResult } from '@/lib/generated-videos'
import {
  filePathFromMediaPath,
  isRemoteGateway,
  mediaExternalUrl,
  mediaName,
  mediaStreamUrl,
  resolveMediaPlaybackSrc
} from '@/lib/media'
import { cn } from '@/lib/utils'

// Aspect hint from the tool args sizes the frame *before* the video loads, so
// the placeholder and the resolved player occupy the same box — no layout shift.
// Video-generate uses ratio strings (`16:9`); also accept image-style names.
function hintedRatio(aspectRatio?: string): number {
  const raw = String(aspectRatio ?? '')
    .toLowerCase()
    .trim()

  if (!raw) {
    return 16 / 9
  }

  if (raw === 'landscape') {
    return 16 / 9
  }

  if (raw === 'portrait') {
    return 9 / 16
  }

  if (raw === 'square') {
    return 1
  }

  const match = raw.match(/^(\d+(?:\.\d+)?)\s*[:/x×]\s*(\d+(?:\.\d+)?)$/)

  if (match) {
    const width = Number(match[1])
    const height = Number(match[2])

    if (width > 0 && height > 0) {
      return width / height
    }
  }

  return 16 / 9
}

function isHttpSrc(path: string): boolean {
  return /^https?:/i.test(path)
}

async function resolveVideoSrc(path: string): Promise<string> {
  // Force playback resolution even when the URL has no `.mp4` suffix — Grok2Api
  // media archives often look like `/v1/media/videos/vid_…` with no extension.
  if (isHttpSrc(path)) {
    return path
  }

  if (window.hermesDesktop && isRemoteGateway()) {
    return mediaExternalUrl(path)
  }

  if (window.hermesDesktop) {
    return mediaStreamUrl(filePathFromMediaPath(path))
  }

  return resolveMediaPlaybackSrc(path)
}

function VideoPlaceholder() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-black/85">
      <div className="size-10 animate-pulse rounded-full border-2 border-white/25 border-t-white/80" />
    </div>
  )
}

export const GeneratedVideo: FC<{ aspectRatio?: string; result?: unknown }> = ({ aspectRatio, result }) => {
  const { t } = useI18n()
  const copy = t.desktop
  const video = result === undefined ? null : generatedVideoFromResult(result)
  const pending = result === undefined

  const [ratio, setRatio] = useState(() => hintedRatio(aspectRatio))
  const [src, setSrc] = useState('')
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => setRatio(hintedRatio(aspectRatio)), [aspectRatio])

  useEffect(() => {
    let cancelled = false

    setFailed(false)
    setReady(false)
    setSrc('')

    if (!video) {
      return
    }

    void resolveVideoSrc(video)
      .then(resolved => {
        if (!cancelled) {
          setSrc(resolved)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setFailed(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [video])

  // Completed but no usable video (generation failed): the agent's prose carries
  // the explanation, so render nothing here.
  if (!pending && !video) {
    return null
  }

  if (failed && video) {
    return (
      <a
        className="mt-2 ref inline-block wrap-anywhere"
        href="#"
        onClick={event => {
          event.preventDefault()
          void window.hermesDesktop?.openExternal(mediaExternalUrl(video))
        }}
      >
        {copy.openVideo}: {mediaName(video)}
      </a>
    )
  }

  return (
    <span
      aria-label={pending ? t.assistant.tool.renderingVideo : undefined}
      aria-live={pending ? 'polite' : undefined}
      className="group/video relative mt-1.5 block max-w-full overflow-hidden rounded-2xl border border-(--ui-stroke-tertiary) bg-black transition-[width,height] duration-300 ease-out"
      data-slot="aui_generated-video"
      role={pending ? 'status' : undefined}
      style={{
        aspectRatio: ratio,
        width: `min(calc(var(--image-preview-height) * ${ratio}), var(--image-preview-max-width), 100%)`
      }}
    >
      {(pending || !ready) && <VideoPlaceholder />}
      {src && (
        <video
          className={cn(
            'absolute inset-0 size-full bg-black object-contain opacity-0 transition-opacity duration-500 ease-out',
            ready && 'opacity-100'
          )}
          controls
          onError={() => setFailed(true)}
          onLoadedMetadata={event => {
            const { videoHeight, videoWidth } = event.currentTarget

            if (videoWidth && videoHeight) {
              setRatio(videoWidth / videoHeight)
            }

            setReady(true)
          }}
          playsInline
          preload="metadata"
          src={src}
        />
      )}
    </span>
  )
}
