import { useRef, useState } from 'react'

/**
 * Card that tracks the cursor with a soft radial highlight.
 *
 * Ported from the Recall-ben branch's reactbits set. That version was TSX and
 * leaned on Tailwind utility classes; this one is JSX with plain CSS, because
 * the rest of this app styles through App.css rather than utilities. Behaviour
 * is unchanged.
 *
 * Chosen over the other components on that branch because it is the only one
 * with no dependencies -- Aurora needs ogl and WebGL, SplitText needs gsap,
 * BlurText needs motion. See DECISIONS.md D10.
 */
export default function SpotlightCard({
  children,
  className = '',
  spotlightColor = 'rgba(139, 92, 246, 0.18)',
  ...rest
}) {
  const ref = useRef(null)
  const [position, setPosition] = useState({ x: 0, y: 0 })
  const [opacity, setOpacity] = useState(0)

  const handleMouseMove = (event) => {
    if (!ref.current) return
    const rect = ref.current.getBoundingClientRect()
    setPosition({ x: event.clientX - rect.left, y: event.clientY - rect.top })
  }

  return (
    <div
      ref={ref}
      className={`spotlight-card ${className}`.trim()}
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setOpacity(1)}
      onMouseLeave={() => setOpacity(0)}
      onFocus={() => setOpacity(1)}
      onBlur={() => setOpacity(0)}
      {...rest}
    >
      <div
        className="spotlight-card-glow"
        aria-hidden="true"
        style={{
          opacity,
          background: `radial-gradient(circle at ${position.x}px ${position.y}px, ${spotlightColor}, transparent 80%)`,
        }}
      />
      {children}
    </div>
  )
}
