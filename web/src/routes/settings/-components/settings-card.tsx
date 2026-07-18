import type { ReactNode } from "react"
import {
  Card,
  CardAction,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"

export function SettingsCard({
  title,
  description,
  action,
  children,
}: {
  title: ReactNode
  description?: ReactNode
  action?: ReactNode
  children: ReactNode
}) {
  return (
    <Card>
      <CardHeader>
        {action && <CardAction>{action}</CardAction>}
        <CardTitle>{title}</CardTitle>
        {description && <CardDescription>{description}</CardDescription>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  )
}
