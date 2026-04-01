import { useParams } from "react-router-dom"

export default function Space() {
  const { slug } = useParams()
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold capitalize">{slug}</h1>
      <p className="text-sm text-gray-500">Space workspace — wired next session.</p>
    </div>
  )
}
