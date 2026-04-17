"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { 
  ChevronLeft, 
  ChevronRight, 
  Calendar as CalendarIcon,
  Clock,
  Plus,
  Video,
  Instagram,
  Youtube,
  Share2,
  TrendingUp,
  Sparkles,
  MoreVertical,
  CheckCircle2,
  Timer
} from "lucide-react";
import {
  format,
  startOfMonth,
  endOfMonth,
  startOfWeek,
  endOfWeek,
  addDays,
  addMonths,
  subMonths,
  isSameMonth,
  isSameDay,
  parseISO
} from "date-fns";

interface ScheduledContent {
  id: string;
  clipId: string;
  title: string;
  scheduledTime: string;
  platforms: string[];
  thumbnail: string;
  status: "scheduled" | "publishing" | "published" | "failed";
  optimalScore: number;
  caption: string;
}

interface CalendarDay {
  date: Date;
  isCurrentMonth: boolean;
  isToday: boolean;
  events: ScheduledContent[];
  optimalSlots: { hour: number; score: number }[];
}

export function ContentCalendar() {
  const [currentDate, setCurrentDate] = useState(new Date());
  const [selectedDate, setSelectedDate] = useState<Date | null>(new Date());
  const [view, setView] = useState<"month" | "week" | "list">("month");
  const [scheduledContent, setScheduledContent] = useState<ScheduledContent[]>([]);

  useEffect(() => {
    // Simulate fetching scheduled content
    const mockContent: ScheduledContent[] = [
      {
        id: "sched_1",
        clipId: "clip_001",
        title: "Tutorial: Advanced Editing",
        scheduledTime: new Date(Date.now() + 86400000 * 2).toISOString(),
        platforms: ["youtube", "tiktok"],
        thumbnail: "/api/placeholder/120/80",
        status: "scheduled",
        optimalScore: 0.92,
        caption: "Learn advanced editing techniques..."
      },
      {
        id: "sched_2",
        clipId: "clip_002",
        title: "Behind the Scenes",
        scheduledTime: new Date(Date.now() + 86400000 * 5).toISOString(),
        platforms: ["instagram", "tiktok"],
        thumbnail: "/api/placeholder/120/80",
        status: "scheduled",
        optimalScore: 0.88,
        caption: "Going behind the scenes of..."
      },
      {
        id: "sched_3",
        clipId: "clip_003",
        title: "Quick Tips Compilation",
        scheduledTime: new Date().toISOString(),
        platforms: ["youtube"],
        thumbnail: "/api/placeholder/120/80",
        status: "publishing",
        optimalScore: 0.95,
        caption: "Best quick tips for creators..."
      }
    ];
    setScheduledContent(mockContent);
  }, []);

  const generateCalendarDays = (): CalendarDay[] => {
    const start = startOfWeek(startOfMonth(currentDate));
    const end = endOfWeek(endOfMonth(currentDate));
    const days: CalendarDay[] = [];
    let day = start;

    while (day <= end) {
      const dayEvents = scheduledContent.filter(event => 
        isSameDay(parseISO(event.scheduledTime), day)
      );

      days.push({
        date: day,
        isCurrentMonth: isSameMonth(day, currentDate),
        isToday: isSameDay(day, new Date()),
        events: dayEvents,
        optimalSlots: dayEvents.length === 0 ? [{ hour: 19, score: 0.9 }] : []
      });
      day = addDays(day, 1);
    }

    return days;
  };

  const getPlatformIcon = (platform: string) => {
    switch (platform) {
      case "youtube": return <Youtube className="h-4 w-4 text-red-600" />;
      case "instagram": return <Instagram className="h-4 w-4 text-pink-600" />;
      case "tiktok": return <Share2 className="h-4 w-4" />;
      default: return <Video className="h-4 w-4" />;
    }
  };

  const getStatusBadge = (status: string) => {
    const variants: Record<string, any> = {
      scheduled: "secondary",
      publishing: "default",
      published: "outline",
      failed: "destructive"
    };
    return <Badge variant={variants[status] || "secondary"}>{status}</Badge>;
  };

  const nextMonth = () => setCurrentDate(addMonths(currentDate, 1));
  const prevMonth = () => setCurrentDate(subMonths(currentDate, 1));

  const calendarDays = generateCalendarDays();

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Content Calendar</h1>
          <p className="text-muted-foreground">
            Schedule and manage your content publication
          </p>
        </div>
        <div className="flex items-center gap-4">
          {/* View Toggle */}
          <div className="flex bg-muted rounded-lg p-1">
            {(["month", "week", "list"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={`px-3 py-1 rounded-md text-sm capitalize ${
                  view === v ? "bg-card shadow-sm" : ""
                }`}
              >
                {v}
              </button>
            ))}
          </div>

          {/* Month Navigation */}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="icon" onClick={prevMonth}>
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <h2 className="text-lg font-semibold min-w-[150px] text-center">
              {format(currentDate, "MMMM yyyy")}
            </h2>
            <Button variant="outline" size="icon" onClick={nextMonth}>
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>

          <Button>
            <Plus className="h-4 w-4 mr-2" />
            Schedule Content
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Calendar Grid */}
        <Card className="lg:col-span-3">
          <CardContent className="p-4">
            {/* Weekday Headers */}
            <div className="grid grid-cols-7 gap-1 mb-2">
              {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(day => (
                <div key={day} className="text-center text-sm font-medium text-muted-foreground py-2">
                  {day}
                </div>
              ))}
            </div>

            {/* Calendar Days */}
            <div className="grid grid-cols-7 gap-1">
              {calendarDays.map((day, idx) => (
                <div
                  key={idx}
                  className={`min-h-[100px] border rounded-lg p-2 cursor-pointer transition-all ${
                    !day.isCurrentMonth ? "bg-muted/30 text-muted-foreground" : ""
                  } ${
                    day.isToday ? "ring-2 ring-primary" : ""
                  } ${
                    selectedDate && isSameDay(day.date, selectedDate) ? "bg-primary/5 border-primary" : ""
                  }`}
                  onClick={() => setSelectedDate(day.date)}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className={`text-sm font-medium ${
                      day.isToday ? "text-primary" : ""
                    }`}>
                      {format(day.date, "d")}
                    </span>
                    {day.optimalSlots.length > 0 && (
                      <Sparkles className="h-3 w-3 text-yellow-500" />
                    )}
                  </div>

                  {/* Events */}
                  <div className="space-y-1">
                    {day.events.slice(0, 3).map(event => (
                      <div
                        key={event.id}
                        className="text-xs p-1 rounded bg-muted truncate"
                      >
                        <div className="flex items-center gap-1">
                          {getPlatformIcon(event.platforms[0])}
                          <span className="truncate">{event.title}</span>
                        </div>
                      </div>
                    ))}
                    {day.events.length > 3 && (
                      <div className="text-xs text-muted-foreground pl-1">
                        +{day.events.length - 3} more
                      </div>
                    )}
                  </div>

                  {/* Optimal Slot Indicator */}
                  {day.optimalSlots.length > 0 && day.events.length === 0 && (
                    <div className="mt-2 text-xs text-yellow-600 flex items-center gap-1">
                      <TrendingUp className="h-3 w-3" />
                      Optimal time
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Stats */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">This Month</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4">
                <div className="text-center p-3 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">{scheduledContent.length}</p>
                  <p className="text-xs text-muted-foreground">Scheduled</p>
                </div>
                <div className="text-center p-3 bg-muted rounded-lg">
                  <p className="text-2xl font-bold">
                    {scheduledContent.filter(c => c.status === "published").length}
                  </p>
                  <p className="text-xs text-muted-foreground">Published</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Selected Day Details */}
          {selectedDate && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm flex items-center gap-2">
                  <CalendarIcon className="h-4 w-4" />
                  {format(selectedDate, "EEEE, MMM do")}
                </CardTitle>
              </CardHeader>
              <CardContent>
                {(() => {
                  const dayEvents = scheduledContent.filter(event =>
                    isSameDay(parseISO(event.scheduledTime), selectedDate)
                  );

                  if (dayEvents.length === 0) {
                    return (
                      <div className="text-center py-8">
                        <p className="text-muted-foreground">No content scheduled</p>
                        <Button variant="outline" size="sm" className="mt-4">
                          <Plus className="h-4 w-4 mr-2" />
                          Schedule for this day
                        </Button>
                      </div>
                    );
                  }

                  return (
                    <div className="space-y-3">
                      {dayEvents.map(event => (
                        <div key={event.id} className="p-3 border rounded-lg">
                          <div className="flex items-start gap-3">
                            <div className="w-20 h-12 bg-muted rounded overflow-hidden flex-shrink-0">
                              {event.thumbnail && (
                                <img src={event.thumbnail} alt="" className="w-full h-full object-cover" />
                              )}
                            </div>
                            <div className="flex-1 min-w-0">
                              <h4 className="font-medium text-sm truncate">{event.title}</h4>
                              <p className="text-xs text-muted-foreground truncate">
                                {event.caption}
                              </p>
                              <div className="flex items-center gap-2 mt-2">
                                {getStatusBadge(event.status)}
                                <div className="flex gap-1">
                                  {event.platforms.map(p => (
                                    <span key={p} className="text-xs">
                                      {getPlatformIcon(p)}
                                    </span>
                                  ))}
                                </div>
                              </div>
                              {event.optimalScore > 0.9 && (
                                <Badge variant="outline" className="mt-2 text-xs">
                                  <Sparkles className="h-3 w-3 mr-1" />
                                  Optimal: {(event.optimalScore * 100).toFixed(0)}%
                                </Badge>
                              )}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  );
                })()}
              </CardContent>
            </Card>
          )}

          {/* Upcoming Queue */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Timer className="h-4 w-4" />
                Publishing Queue
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3 max-h-[300px] overflow-y-auto">
                {scheduledContent
                  .filter(c => c.status === "scheduled" || c.status === "publishing")
                  .slice(0, 5)
                  .map(event => (
                    <div key={event.id} className="flex items-center gap-3 p-2 bg-muted rounded-lg">
                      <div className="flex-shrink-0">
                        {getPlatformIcon(event.platforms[0])}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium truncate">{event.title}</p>
                        <p className="text-xs text-muted-foreground">
                          {format(parseISO(event.scheduledTime), "MMM d, h:mm a")}
                        </p>
                      </div>
                      {event.status === "publishing" ? (
                        <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                      ) : (
                        <CheckCircle2 className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                  ))}

                {scheduledContent.filter(c => c.status === "scheduled" || c.status === "publishing").length === 0 && (
                  <p className="text-sm text-muted-foreground text-center py-4">
                    No upcoming publications
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Optimal Times */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <TrendingUp className="h-4 w-4" />
                Best Times to Post
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                <div className="flex items-center justify-between p-2 bg-green-50 rounded-lg">
                  <span className="text-sm">Lunch Time</span>
                  <Badge variant="outline" className="text-xs">12:00 PM</Badge>
                </div>
                <div className="flex items-center justify-between p-2 bg-green-50 rounded-lg">
                  <span className="text-sm">Evening Peak</span>
                  <Badge variant="outline" className="text-xs">7:00 PM</Badge>
                </div>
                <div className="flex items-center justify-between p-2 bg-yellow-50 rounded-lg">
                  <span className="text-sm">Late Night</span>
                  <Badge variant="outline" className="text-xs">10:00 PM</Badge>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
