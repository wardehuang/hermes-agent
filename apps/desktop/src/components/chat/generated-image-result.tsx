'use client'

import { type FC, useState } from 'react'

import { useElapsedSeconds } from '@/components/chat/activity-timer'
import { ActivityTimerText } from '@/components/chat/activity-timer-text'
import { DiffusionCanvas } from '@/components/chat/image-generation-placeholder'
import { ImageActionButton, ImageLightbox } from '@/components/chat/zoomable-image'
import { useImageDownload } from '@/hooks/use-image-download'
import { useMediaImage } from '@/hooks/use-media-image'
import { useI18n } from '@/i18n'
import { generatedImageDimensionsFromResult, generatedImagesFromResult } from '@/lib/generated-images'
import { mediaExternalUrl, mediaName } from '@/lib/media'
import { cn } from '@/lib/utils'

// A hint is only a placeholder shape, not a promise about the delivered image.
const ASPECT_HINTS: Record<string, number> = {
  landscape: 16 / 9,
  square: 1,
  portrait: 9 / 16,
  '1:1': 1,
  '16:9': 16 / 9,
  '9:16': 9 / 16,
  '4:3': 4 / 3,
  '3:4': 3 / 4,
  '3:2': 3 / 2,
  '2:3': 2 / 3
}

function hintedRatio(aspectRatio?: string): number {
  const raw = String(aspectRatio ?? '')
    .toLowerCase()
    .trim()
  const named = ASPECT_HINTS[raw]

  if (named) {
    return named
  }

  const ratio = raw.match(/^(\d+(?:\.\d+)?)\s*:\s*(\d+(?:\.\d+)?)$/)

  if (ratio) {
    const width = Number(ratio[1])
    const height = Number(ratio[2])

    if (width > 0 && height > 0) {
      return width / height
    }
  }

  const pixels = raw.match(/^(\d+)\s*[x×]\s*(\d+)$/i)

  if (pixels) {
    const width = Number(pixels[1])
    const height = Number(pixels[2])

    if (width > 0 && height > 0) {
      return width / height
    }
  }

  return ASPECT_HINTS.landscape
}

const GeneratedImageCard: FC<{
  aspectRatio?: string
  dimensions?: ReturnType<typeof generatedImageDimensionsFromResult>
  image: null | string
  pending: boolean
  startedAt?: number
}> = ({ aspectRatio, dimensions, image, pending, startedAt }) => {
  const { t } = useI18n()
  const copy = t.desktop
  const elapsed = useElapsedSeconds(pending, undefined, startedAt)

  const media = useMediaImage(image ?? '', hintedRatio(aspectRatio), dimensions, {
    preservePendingFrame: true
  })

  const { src, loaded, failed } = media
  const [canvasGone, setCanvasGone] = useState<string | null>(null)
  const [lightboxOpen, setLightboxOpen] = useState<string | null>(null)
  const { download, saving } = useImageDownload(src)

  // Completed but no usable image (generation failed): the agent's prose carries
  // the explanation, so render nothing here.
  if (!pending && !image) {
    return null
  }

  // Nothing will fill the frame, so collapse to the link line.
  if (failed && image) {
    return (
      <a
        className="mt-2 ref inline-block wrap-anywhere"
        href="#"
        onClick={event => {
          event.preventDefault()
          void window.hermesDesktop?.openExternal(mediaExternalUrl(image))
        }}
      >
        {copy.openImage}: {mediaName(image)}
      </a>
    )
  }

  return (
    <>
      <span
        aria-label={pending ? t.assistant.tool.renderingImage : undefined}
        aria-live={pending ? 'polite' : undefined}
        className="group/image relative block max-w-full overflow-hidden rounded-2xl"
        data-slot="aui_generated-image"
        role={pending ? 'status' : undefined}
        style={{
          ...media.frameStyle,
          ...(pending ? { minHeight: '12rem' } : {})
        }}
      >
        {canvasGone !== media.key && (
          <div
            className={cn('absolute inset-0 transition-opacity duration-500 ease-out', loaded && 'opacity-0')}
            onTransitionEnd={() => loaded && setCanvasGone(media.key)}
          >
            <DiffusionCanvas />
          </div>
        )}
        {src && (
          <button
            aria-label={copy.openImage}
            className="absolute inset-0 block size-full cursor-zoom-in"
            onClick={() => setLightboxOpen(media.key)}
            type="button"
          >
            <img
              alt="Generated image"
              className={cn(
                'absolute inset-0 size-full object-contain opacity-0 transition-opacity duration-500 ease-out',
                loaded && 'opacity-100'
              )}
              draggable={false}
              onError={media.onError}
              onLoad={event => media.onLoad(event.currentTarget)}
              src={src}
            />
          </button>
        )}
        {loaded && src && (
          <ImageActionButton className="group-hover/image:opacity-100" copy={copy} onClick={download} saving={saving} />
        )}
        {pending && (
          <span className="pointer-events-none absolute bottom-2 left-2 z-10">
            <ActivityTimerText seconds={elapsed} />
          </span>
        )}
      </span>
      {src && (
        <ImageLightbox
          alt="Generated image"
          copy={copy}
          onClick={download}
          onOpenChange={open => setLightboxOpen(open ? media.key : null)}
          open={lightboxOpen === media.key}
          saving={saving}
          src={src}
        />
      )}
    </>
  )
}

export const GeneratedImage: FC<{ aspectRatio?: string; result?: unknown; startedAt?: number }> = ({
  aspectRatio,
  result,
  startedAt
}) => {
  const pending = result === undefined
  const images = pending ? [null] : generatedImagesFromResult(result)
  const dimensions = generatedImageDimensionsFromResult(result)

  if (!pending && images.length === 0) {
    return null
  }

  const cards = images.map((image, index) => (
    <GeneratedImageCard
      aspectRatio={aspectRatio}
      dimensions={dimensions}
      image={image}
      key={image ?? `pending-${index}`}
      pending={pending}
      startedAt={startedAt}
    />
  ))

  if (cards.length <= 1) {
    return cards[0] ?? null
  }

  return <div className="flex flex-col gap-2">{cards}</div>
}
