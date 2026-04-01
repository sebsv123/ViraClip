"use client";

import { useEffect, useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { 
  Trophy, 
  Star, 
  Zap, 
  Target,
  Flame,
  Crown,
  Medal,
  Award,
  Lock,
  CheckCircle2
} from "lucide-react";

interface GamificationData {
  totalPoints: number;
  currentLevel: number;
  rank: string;
  streakDays: number;
  achievementsEarned: number;
  achievementsTotal: number;
  badges: string[];
  unlockedFeatures: string[];
  levelProgress: number;
  nextLevelPoints: number;
  achievements: Achievement[];
  leaderboard: LeaderboardEntry[];
}

interface Achievement {
  id: string;
  name: string;
  description: string;
  icon: string;
  points: number;
  rarity: "common" | "rare" | "epic" | "legendary";
  earned: boolean;
  earnedAt?: string;
}

interface LeaderboardEntry {
  rank: number;
  userId: string;
  totalPoints: number;
  level: number;
  achievementsCount: number;
}

export function GamificationPanel() {
  const [data, setData] = useState<GamificationData | null>(null);

  useEffect(() => {
    fetchGamificationData();
  }, []);

  const fetchGamificationData = async () => {
    try {
      const response = await fetch("/api/gamification/profile");
      const profileData = await response.json();
      setData(profileData);
    } catch (error) {
      console.error("Failed to fetch gamification data:", error);
    }
  };

  if (!data) {
    return (
      <div className="space-y-4 p-4">
        <Card className="animate-pulse h-40" />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => (
            <Card key={i} className="animate-pulse h-32" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">Achievements & Rewards</h1>
          <p className="text-muted-foreground">
            Level up by creating amazing content
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="secondary" className="text-lg px-4 py-2">
            <Crown className="h-4 w-4 mr-2" />
            {data.rank}
          </Badge>
        </div>
      </div>

      {/* Level Progress */}
      <Card className="bg-gradient-to-r from-purple-600 to-blue-600 text-white">
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-white/20 flex items-center justify-center">
                <span className="text-2xl font-bold">{data.currentLevel}</span>
              </div>
              <div>
                <h2 className="text-xl font-bold">Level {data.currentLevel}</h2>
                <p className="text-white/80">
                  {data.totalPoints.toLocaleString()} total points
                </p>
              </div>
            </div>
            <div className="text-right">
              <p className="text-sm text-white/80">Next level</p>
              <p className="font-bold">{data.nextLevelPoints.toLocaleString()} pts</p>
            </div>
          </div>
          <Progress 
            value={data.levelProgress * 100} 
            className="h-3 bg-white/20"
          />
          <p className="text-sm text-white/80 mt-2 text-center">
            {Math.round(data.levelProgress * 100)}% to Level {data.currentLevel + 1}
          </p>
        </CardContent>
      </Card>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatCard
          icon={<Trophy className="h-5 w-5 text-yellow-500" />}
          value={data.totalPoints.toLocaleString()}
          label="Total Points"
        />
        <StatCard
          icon={<Flame className="h-5 w-5 text-orange-500" />}
          value={data.streakDays.toString()}
          label="Day Streak"
        />
        <StatCard
          icon={<Award className="h-5 w-5 text-blue-500" />}
          value={`${data.achievementsEarned}/${data.achievementsTotal}`}
          label="Achievements"
        />
        <StatCard
          icon={<Star className="h-5 w-5 text-purple-500" />}
          value={data.badges.length.toString()}
          label="Badges Earned"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Achievements */}
        <div className="lg:col-span-2 space-y-4">
          <h2 className="text-xl font-semibold flex items-center gap-2">
            <Medal className="h-5 w-5" />
            Achievements
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {data.achievements.map((achievement) => (
              <AchievementCard 
                key={achievement.id} 
                achievement={achievement} 
              />
            ))}
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Leaderboard */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Target className="h-4 w-4" />
                Top Creators
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                {data.leaderboard.slice(0, 5).map((entry) => (
                  <div 
                    key={entry.userId}
                    className={`flex items-center gap-3 p-2 rounded-lg ${
                      entry.rank === 1 ? "bg-yellow-50" :
                      entry.rank === 2 ? "bg-gray-50" :
                      entry.rank === 3 ? "bg-orange-50" : ""
                    }`}
                  >
                    <div className={`
                      w-8 h-8 rounded-full flex items-center justify-center font-bold text-sm
                      ${entry.rank === 1 ? "bg-yellow-500 text-white" :
                        entry.rank === 2 ? "bg-gray-400 text-white" :
                        entry.rank === 3 ? "bg-orange-400 text-white" :
                        "bg-muted text-muted-foreground"}
                    `}>
                      {entry.rank}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="font-medium truncate">Creator {entry.userId.slice(-4)}</p>
                      <p className="text-xs text-muted-foreground">
                        Level {entry.level} • {entry.totalPoints.toLocaleString()} pts
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Unlocked Features */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Zap className="h-4 w-4" />
                Unlocked Features
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {data.unlockedFeatures.map((feature) => (
                  <div 
                    key={feature}
                    className="flex items-center gap-2 text-sm"
                  >
                    <CheckCircle2 className="h-4 w-4 text-green-500" />
                    <span className="capitalize">{feature.replace("_", " ")}</span>
                  </div>
                ))}
                {data.unlockedFeatures.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    Keep leveling up to unlock features!
                  </p>
                )}
              </div>
            </CardContent>
          </Card>

          {/* Badges */}
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Star className="h-4 w-4" />
                Badge Collection
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-2">
                {data.badges.map((badge, i) => (
                  <Badge key={i} variant="secondary" className="text-lg px-3 py-1">
                    {badge}
                  </Badge>
                ))}
                {data.badges.length === 0 && (
                  <p className="text-sm text-muted-foreground">
                    Earn rare achievements to collect badges
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

function StatCard({ 
  icon, 
  value, 
  label 
}: { 
  icon: React.ReactNode; 
  value: string; 
  label: string;
}) {
  return (
    <Card>
      <CardContent className="p-4 flex items-center gap-4">
        <div className="p-2 bg-muted rounded-lg">{icon}</div>
        <div>
          <p className="text-2xl font-bold">{value}</p>
          <p className="text-sm text-muted-foreground">{label}</p>
        </div>
      </CardContent>
    </Card>
  );
}

function AchievementCard({ achievement }: { achievement: Achievement }) {
  const rarityColors = {
    common: "bg-gray-100 border-gray-200",
    rare: "bg-blue-50 border-blue-200",
    epic: "bg-purple-50 border-purple-200",
    legendary: "bg-yellow-50 border-yellow-200",
  };

  const rarityIcons = {
    common: <div className="w-2 h-2 rounded-full bg-gray-400" />,
    rare: <div className="w-2 h-2 rounded-full bg-blue-500" />,
    epic: <div className="w-2 h-2 rounded-full bg-purple-500" />,
    legendary: <div className="w-2 h-2 rounded-full bg-yellow-500" />,
  };

  return (
    <Card className={`${achievement.earned ? rarityColors[achievement.rarity] : "bg-muted/50"} ${!achievement.earned ? "opacity-75" : ""}`}>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className="text-3xl">{achievement.icon}</div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <h3 className="font-semibold truncate">{achievement.name}</h3>
              {achievement.earned ? (
                <CheckCircle2 className="h-4 w-4 text-green-500" />
              ) : (
                <Lock className="h-4 w-4 text-muted-foreground" />
              )}
            </div>
            <p className="text-sm text-muted-foreground line-clamp-2">
              {achievement.description}
            </p>
            <div className="flex items-center gap-3 mt-2">
              {rarityIcons[achievement.rarity]}
              <span className="text-xs text-muted-foreground capitalize">
                {achievement.rarity}
              </span>
              <Badge variant="secondary" className="text-xs">
                +{achievement.points} pts
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
