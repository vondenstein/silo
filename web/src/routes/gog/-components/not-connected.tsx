import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Link } from "@tanstack/react-router"

export function NotConnected() {
  return (
    <div className="flex flex-1 flex-col items-center justify-start px-4 pt-16 md:pt-24">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>GOG Isn't Connected</CardTitle>
          <CardDescription>
            Connect your GOG account to browse and import your owned library.
          </CardDescription>
        </CardHeader>
        <CardFooter>
          <Button asChild className="w-full">
            <Link to="/settings" search={{ tab: "gog" }}>
              Configure GOG
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
