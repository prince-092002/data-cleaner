class OSA:
    @staticmethod
    def distance(s1, s2):
        n, m = len(s1), len(s2)
        d = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(n + 1): d[i][0] = i
        for j in range(m + 1): d[0][j] = j
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                c = 0 if s1[i-1] == s2[j-1] else 1
                d[i][j] = min(d[i-1][j] + 1, d[i][j-1] + 1, d[i-1][j-1] + c)
                if i > 1 and j > 1 and s1[i-1] == s2[j-2] and s1[i-2] == s2[j-1]:
                    d[i][j] = min(d[i][j], d[i-2][j-2] + 1)
        return d[n][m]
